"""Krea 2 Tiled Diffusion core engine for FiL_Design_ImageMind.

Contains pure tensor math and execution primitives for:
1. Tile geometry planning and raised cosine taper weighting.
2. RoPE positional offset patching.
3. Edge-Aware Adaptive Texture Injection (Sobel saliency masking).
4. Color and luminance matching (luminance / wavelet).
5. Per-tile vision conditioning and tiled KSampler denoise execution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import math
from typing import Any

import torch
import torch.nn.functional as F

import comfy.model_management
import comfy.sample
import comfy.samplers
import comfy.sd
import comfy.utils
import folder_paths

logger = logging.getLogger(__name__)

LATENT_SCALE = 8
KREA2_PATCH_SIZE = 2
TILE_GRIDS = ["1x1", "1x2", "2x1", "2x2", "2x3", "3x2", "3x3", "4x4"]
ALL_TILE_GRIDS = ["auto"] + TILE_GRIDS
DEFAULT_TILE_GRID = "2x2"
DEFAULT_TILE_OVERLAP_PIXELS = 256
TAPER_FLOOR = 0.0001
POSITIVE_ROW = 0


@dataclass(frozen=True)
class LatentTile:
    """One tile's place on the latent canvas, in latent cells."""
    column_start: int
    row_start: int
    width: int
    height: int


@dataclass(frozen=True)
class LatentTilePlan:
    """Everything the denoise loop needs, and what the geometry actually became."""
    tiles: list[LatentTile]
    tile_width: int
    tile_height: int
    overlap: int
    columns: int
    rows: int


def calculate_auto_tile_grid(latent_width: int, latent_height: int,
                             max_tile_dim_pixels: int = 1024) -> str:
    """Selects the smallest grid so tile sizes do not exceed max_tile_dim_pixels."""
    max_latent = max_tile_dim_pixels // LATENT_SCALE
    cols = max(1, math.ceil(latent_width / max_latent))
    rows = max(1, math.ceil(latent_height / max_latent))
    grid_str = f"{cols}x{rows}"
    if grid_str in TILE_GRIDS:
        return grid_str
    cols = min(4, max(1, cols))
    rows = min(4, max(1, rows))
    clamped = f"{cols}x{rows}"
    return clamped if clamped in TILE_GRIDS else "2x2"


def calculate_tiles(latent_width: int, latent_height: int, tile_grid: str,
                    overlap_pixels: int = DEFAULT_TILE_OVERLAP_PIXELS) -> LatentTilePlan:
    """Calculates tiles and overlap for a given latent dimension and grid."""
    if tile_grid == "auto":
        tile_grid = calculate_auto_tile_grid(latent_width, latent_height)

    cols_str, rows_str = tile_grid.split("x")
    columns, rows = int(cols_str), int(rows_str)

    req_overlap = max(0, int(round(overlap_pixels / LATENT_SCALE)))
    tile_w = math.ceil((latent_width + (columns - 1) * req_overlap) / columns)
    tile_h = math.ceil((latent_height + (rows - 1) * req_overlap) / rows)

    overlap_x = 0 if columns <= 1 else math.ceil((columns * tile_w - latent_width) / (columns - 1))
    overlap_y = 0 if rows <= 1 else math.ceil((rows * tile_h - latent_height) / (rows - 1))
    overlap = max(overlap_x, overlap_y)

    tiles: list[LatentTile] = []
    for r in range(rows):
        r_start = 0 if rows <= 1 else round(r * (latent_height - tile_h) / (rows - 1))
        for c in range(columns):
            c_start = 0 if columns <= 1 else round(c * (latent_width - tile_w) / (columns - 1))
            tiles.append(LatentTile(column_start=c_start, row_start=r_start, width=tile_w, height=tile_h))

    return LatentTilePlan(tiles=tiles, tile_width=tile_w, tile_height=tile_h,
                          overlap=overlap, columns=columns, rows=rows)


def raised_cosine_taper(index: int, length: int) -> float:
    """Taper weight across [0, length-1] smoothly falling off at borders."""
    if length <= 1:
        return 1.0
    half = length / 2.0
    dist = abs(index + 0.5 - half)
    taper = 0.5 * (1.0 + math.cos(math.pi * dist / half))
    return max(TAPER_FLOOR, taper)


def build_tile_fusion_weight(tile_height: int, tile_width: int, latent_rank: int,
                             device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    """Raised cosine outer-product weight tensor shaped to broadcast over latent."""
    row_taper = torch.tensor([raised_cosine_taper(r, tile_height) for r in range(tile_height)],
                             device=device, dtype=dtype)
    col_taper = torch.tensor([raised_cosine_taper(c, tile_width) for c in range(tile_width)],
                             device=device, dtype=dtype)
    leading_singletons = (1,) * max(0, latent_rank - 2)
    return torch.outer(row_taper, col_taper).reshape(*leading_singletons, tile_height, tile_width)


@dataclass
class TileRopeOffsetHolder:
    """Offset for RoPE position IDs per tile."""
    row_offset_tokens: int = 0
    column_offset_tokens: int = 0
    batch_offsets: list[tuple[int, int]] | None = None

    def set_to_tile_origin(self, row_start: int, column_start: int) -> None:
        self.row_offset_tokens = int(row_start) // KREA2_PATCH_SIZE
        self.column_offset_tokens = int(column_start) // KREA2_PATCH_SIZE
        self.batch_offsets = None

    def set_to_batch_origins(self, origins: list[tuple[int, int]]) -> None:
        self.batch_offsets = [
            (int(r) // KREA2_PATCH_SIZE, int(c) // KREA2_PATCH_SIZE)
            for r, c in origins
        ]
        self.row_offset_tokens = 0
        self.column_offset_tokens = 0

    def clear(self) -> None:
        self.row_offset_tokens = 0
        self.column_offset_tokens = 0
        self.batch_offsets = None


def build_post_input_rope_offset_patch(holder: TileRopeOffsetHolder):
    """Post-input patch shifting image position IDs to true canvas coordinates."""
    def patch(args: dict[str, Any]) -> dict[str, Any]:
        img_ids = args.get("img_ids")
        if img_ids is None:
            return args

        if holder.batch_offsets is not None:
            b_size = img_ids.shape[0]
            if len(holder.batch_offsets) == b_size:
                r_offsets = torch.tensor([o[0] for o in holder.batch_offsets],
                                         dtype=img_ids.dtype, device=img_ids.device).view(b_size, 1)
                c_offsets = torch.tensor([o[1] for o in holder.batch_offsets],
                                         dtype=img_ids.dtype, device=img_ids.device).view(b_size, 1)
                shifted = img_ids.clone()
                shifted[..., 1] += r_offsets
                shifted[..., 2] += c_offsets
                return {**args, "img_ids": shifted}

        if holder.row_offset_tokens == 0 and holder.column_offset_tokens == 0:
            return args

        shifted = img_ids.clone()
        shifted[..., 1] += holder.row_offset_tokens
        shifted[..., 2] += holder.column_offset_tokens
        return {**args, "img_ids": shifted}

    return patch


def substitute_tile_conditioning_for_positive_rows(step_conditioning: dict,
                                                   cond_or_uncond: list[int],
                                                   tile_conditioning):
    """Substitutes tile-specific cross-attention embeddings into positive batch rows."""
    batched_embedding = step_conditioning.get("c_crossattn")
    if batched_embedding is None or not cond_or_uncond:
        return step_conditioning
    if POSITIVE_ROW not in cond_or_uncond:
        return step_conditioning

    tile_embedding = tile_conditioning[0][0].to(device=batched_embedding.device,
                                                dtype=batched_embedding.dtype)

    if all(row_kind == POSITIVE_ROW for row_kind in cond_or_uncond):
        substituted = tile_embedding.repeat(len(cond_or_uncond), 1, 1) if tile_embedding.shape[0] == 1 else tile_embedding
        return {**step_conditioning, "c_crossattn": substituted}

    if tile_embedding.shape[1] != batched_embedding.shape[1]:
        return step_conditioning

    substituted = batched_embedding.clone()
    for row_index, row_kind in enumerate(cond_or_uncond):
        if row_kind == POSITIVE_ROW:
            substituted[row_index] = tile_embedding[0]
    return {**step_conditioning, "c_crossattn": substituted}


def denoise_latent_as_fused_tiles(apply_model, latent: torch.Tensor,
                                  timestep, conditioning: dict,
                                  plan: LatentTilePlan,
                                  rope_offset_holder: TileRopeOffsetHolder | None,
                                  cond_or_uncond: list[int] | None = None,
                                  conditioning_per_tile: list | None = None,
                                  tile_batch_size: int = 1) -> torch.Tensor:
    """Denoises one step as overlapping tiles fused under raised cosine weights."""
    weight = build_tile_fusion_weight(plan.tile_height, plan.tile_width,
                                      latent.dim(), latent.device, latent.dtype)

    accumulator = torch.zeros_like(latent)
    weight_sum = torch.zeros_like(latent)

    num_tiles = len(plan.tiles)
    can_batch = (
        tile_batch_size > 1
        and conditioning_per_tile is None
        and (rope_offset_holder is None or hasattr(rope_offset_holder, "set_to_batch_origins"))
    )

    if can_batch:
        for batch_start in range(0, num_tiles, tile_batch_size):
            batch_slice = plan.tiles[batch_start:batch_start + tile_batch_size]
            b_actual = len(batch_slice)

            tile_stacks = [latent[..., t.row_start:t.row_start + t.height,
                                  t.column_start:t.column_start + t.width] for t in batch_slice]
            batched_tiles = torch.cat(tile_stacks, dim=0)

            if rope_offset_holder is not None:
                rope_offset_holder.set_to_batch_origins([(t.row_start, t.column_start) for t in batch_slice])

            batched_cond = {}
            for k, v in conditioning.items():
                if isinstance(v, torch.Tensor):
                    batched_cond[k] = v.repeat(b_actual, *([1] * (v.dim() - 1)))
                else:
                    batched_cond[k] = v

            denoised_batch = apply_model(batched_tiles, timestep, **batched_cond)
            if rope_offset_holder is not None:
                rope_offset_holder.clear()

            split_tiles = torch.chunk(denoised_batch, b_actual, dim=0)
            for idx, t in enumerate(batch_slice):
                accumulator[..., t.row_start:t.row_start + t.height,
                            t.column_start:t.column_start + t.width] += split_tiles[idx] * weight
                weight_sum[..., t.row_start:t.row_start + t.height,
                           t.column_start:t.column_start + t.width] += weight
    else:
        for tile_idx, tile in enumerate(plan.tiles):
            tile_latent = latent[..., tile.row_start:tile.row_start + tile.height,
                                 tile.column_start:tile.column_start + tile.width]

            if conditioning_per_tile is not None and cond_or_uncond is not None:
                tile_cond = substitute_tile_conditioning_for_positive_rows(
                    conditioning, cond_or_uncond, conditioning_per_tile[tile_idx])
            else:
                tile_cond = conditioning

            if rope_offset_holder is not None:
                rope_offset_holder.set_to_tile_origin(tile.row_start, tile.column_start)

            denoised_tile = apply_model(tile_latent, timestep, **tile_cond)

            if rope_offset_holder is not None:
                rope_offset_holder.clear()

            accumulator[..., tile.row_start:tile.row_start + tile.height,
                        tile.column_start:tile.column_start + tile.width] += denoised_tile * weight
            weight_sum[..., tile.row_start:tile.row_start + tile.height,
                       tile.column_start:tile.column_start + tile.width] += weight

    return accumulator / weight_sum


def run_upscale_model(upscale_model, image: torch.Tensor) -> torch.Tensor:
    """Tiled execution of ESRGAN/DAT2 upscale models to prevent VRAM OOM."""
    device = comfy.model_management.get_torch_device()
    upscale_model.to(device)
    in_img = image.movedim(-1, -3).to(device)

    tile = 512
    overlap = 32
    output_device = comfy.model_management.intermediate_device()

    oom = True
    while oom:
        try:
            steps = in_img.shape[0] * comfy.utils.get_tiled_scale_steps(
                in_img.shape[3], in_img.shape[2], tile_x=tile, tile_y=tile, overlap=overlap)
            pbar = comfy.utils.ProgressBar(steps)
            s = comfy.utils.tiled_scale(
                in_img, lambda a: upscale_model(a.float()),
                tile_x=tile, tile_y=tile, overlap=overlap,
                upscale_amount=upscale_model.scale, pbar=pbar, output_device=output_device)
            oom = False
        except Exception as e:
            comfy.model_management.raise_non_oom(e)
            tile //= 2
            if tile < 128:
                raise e

    return torch.clamp(s.movedim(-3, -1), min=0.0, max=1.0).to(image.dtype)


def scale_image_by_factor(image: torch.Tensor, factor: float,
                          upscale_model=None, upscale_method: str = "lanczos") -> torch.Tensor:
    """Upscales IMAGE tensor by factor, ensuring dimensions are multiples of 16."""
    if image is None:
        return image
    samples = image.movedim(-1, 1)
    target_width = max(16, int(round(samples.shape[3] * factor / 16.0)) * 16)
    target_height = max(16, int(round(samples.shape[2] * factor / 16.0)) * 16)

    if upscale_model is not None:
        logger.info("FiLKrea2TiledDiffusion: upscaling image with AI upscale model")
        model_upscaled = run_upscale_model(upscale_model, image[:, :, :, :3])
        if model_upscaled.shape[2] != target_width or model_upscaled.shape[1] != target_height:
            resized = comfy.utils.common_upscale(
                model_upscaled.movedim(-1, 1), target_width, target_height,
                "lanczos", "disabled")
            return resized.movedim(1, -1)[:, :, :, :3]
        return model_upscaled

    resized = comfy.utils.common_upscale(samples, target_width, target_height,
                                         upscale_method, "disabled")
    return resized.movedim(1, -1)[:, :, :, :3]


def apply_edge_aware_texture(base_image: torch.Tensor, reference_image: torch.Tensor,
                             blend_strength: float = 0.20, filter_radius: int = 3) -> torch.Tensor:
    """Injects edge-aware high-pass microtexture using Sobel saliency masking."""
    if blend_strength <= 0.0 or reference_image is None or base_image is None:
        return base_image

    if base_image.shape[1:3] != reference_image.shape[1:3]:
        ref = comfy.utils.common_upscale(
            reference_image.movedim(-1, 1), base_image.shape[2], base_image.shape[1],
            "lanczos", "disabled").movedim(1, -1)[:, :, :, :3]
    else:
        ref = reference_image[:, :, :, :3]

    ref_ch = ref.movedim(-1, 1).to(base_image.device, dtype=torch.float32)
    base_ch = base_image[:, :, :, :3].movedim(-1, 1).to(torch.float32)

    # 1. High-pass filter of reference
    kernel_size = filter_radius * 2 + 1
    sigma = filter_radius / 2.0
    x = torch.arange(kernel_size, dtype=torch.float32, device=base_image.device) - filter_radius
    gauss = torch.exp(-0.5 * (x / sigma) ** 2)
    k1d = gauss / gauss.sum()
    k2d = torch.outer(k1d, k1d).unsqueeze(0).unsqueeze(0).repeat(3, 1, 1, 1)

    pad = filter_radius
    padded = F.pad(ref_ch, (pad, pad, pad, pad), mode='reflect')
    low_pass = F.conv2d(padded, k2d, groups=3)
    high_pass = ref_ch - low_pass

    # 2. Sobel edge magnitude
    gray = 0.299 * ref_ch[:, 0:1] + 0.587 * ref_ch[:, 1:2] + 0.114 * ref_ch[:, 2:3]
    kx = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=torch.float32, device=base_image.device).unsqueeze(0).unsqueeze(0)
    ky = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=torch.float32, device=base_image.device).unsqueeze(0).unsqueeze(0)

    gx = F.conv2d(gray, kx, padding=1)
    gy = F.conv2d(gray, ky, padding=1)
    edge_mag = torch.sqrt(gx**2 + gy**2)

    edge_norm = torch.clamp((edge_mag - 0.03) / 0.18, 0.0, 1.0)
    smooth_mask = edge_norm * edge_norm * (3.0 - 2.0 * edge_norm)

    floor_strength = blend_strength * 0.15
    boost_strength = blend_strength * 1.40
    adaptive_weight = floor_strength + ((boost_strength - floor_strength) * smooth_mask)

    injected = base_ch + (high_pass * adaptive_weight)
    return torch.clamp(injected.movedim(1, -1), 0.0, 1.0).to(base_image.dtype)


def apply_color_matching(reference_image: torch.Tensor, generated_image: torch.Tensor,
                         mode: str = "none") -> torch.Tensor:
    """Locks colors / skin tones of generated_image to reference_image."""
    if mode == "none" or reference_image is None or generated_image is None:
        return generated_image

    ref = reference_image[:, :, :, :3].to(generated_image.device, dtype=torch.float32)
    gen = generated_image[:, :, :, :3].to(torch.float32)

    if ref.shape[1:3] != gen.shape[1:3]:
        ref = comfy.utils.common_upscale(
            ref.movedim(-1, 1), gen.shape[2], gen.shape[1],
            "lanczos", "disabled").movedim(1, -1)

    if mode == "luminance":
        mat_rgb2ycbcr = torch.tensor([
            [ 0.299000,  0.587000,  0.114000],
            [-0.168736, -0.331264,  0.500000],
            [ 0.500000, -0.418688, -0.081312]
        ], device=gen.device, dtype=torch.float32)
        mat_ycbcr2rgb = torch.inverse(mat_rgb2ycbcr)

        ycbcr_ref = torch.matmul(ref, mat_rgb2ycbcr.T)
        ycbcr_gen = torch.matmul(gen, mat_rgb2ycbcr.T)

        matched = torch.cat([ycbcr_gen[..., 0:1], ycbcr_ref[..., 1:3]], dim=-1)
        rgb_matched = torch.matmul(matched, mat_ycbcr2rgb.T)
        return torch.clamp(rgb_matched, 0.0, 1.0).to(generated_image.dtype)

    elif mode == "wavelet":
        gen_ch = gen.movedim(-1, 1)
        ref_ch = ref.movedim(-1, 1)

        k_size = 7
        pad = k_size // 2
        kernel = torch.ones((1, 1, k_size, k_size), device=gen.device, dtype=torch.float32) / (k_size * k_size)
        kernel = kernel.repeat(3, 1, 1, 1)

        padded_gen = F.pad(gen_ch, (pad, pad, pad, pad), mode='reflect')
        padded_ref = F.pad(ref_ch, (pad, pad, pad, pad), mode='reflect')

        low_gen = F.conv2d(padded_gen, kernel, groups=3)
        low_ref = F.conv2d(padded_ref, kernel, groups=3)
        high_gen = gen_ch - low_gen

        matched_ch = low_ref + high_gen
        return torch.clamp(matched_ch.movedim(1, -1), 0.0, 1.0).to(generated_image.dtype)

    return generated_image
