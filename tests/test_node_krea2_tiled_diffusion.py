"""Tests for FiLKrea2TiledDiffusion node, its schema and engine algorithms."""
from __future__ import annotations

import json
from pathlib import Path
import torch

from FiL_Design_ImageMind.common.krea2_engine import (
    ALL_TILE_GRIDS,
    apply_color_matching,
    apply_edge_aware_texture,
    calculate_auto_tile_grid,
    calculate_tiles,
)
from FiL_Design_ImageMind.common.release_gate import RELEASE_NODES
from FiL_Design_ImageMind.nodes.node_krea2_tiled_diffusion import FiLKrea2TiledDiffusion


def test_schema_definition():
    schema = FiLKrea2TiledDiffusion.define_schema()
    assert schema.node_id == "FiLKrea2TiledDiffusion"
    assert "Krea 2" in schema.display_name

    input_ids = [inp.id for inp in schema.inputs]
    assert "model" in input_ids
    assert "clip" in input_ids
    assert "vae" in input_ids
    assert "image" in input_ids
    assert "prompt" in input_ids
    assert "denoise" in input_ids
    assert "tile_grid" in input_ids
    assert "texture_injection" in input_ids
    assert "color_match" in input_ids

    output_names = [out.display_name for out in schema.outputs]
    assert "image" in output_names
    assert "latent" in output_names


def test_tile_calculation():
    plan = calculate_tiles(latent_width=128, latent_height=128, tile_grid="2x2", overlap_pixels=256)
    assert len(plan.tiles) == 4
    assert plan.columns == 2
    assert plan.rows == 2
    assert plan.tile_width > 0
    assert plan.tile_height > 0


def test_auto_tile_grid():
    grid = calculate_auto_tile_grid(latent_width=64, latent_height=64)
    assert grid in ALL_TILE_GRIDS


def test_edge_aware_texture_injection():
    base = torch.full((1, 64, 64, 3), 0.5, dtype=torch.float32)
    ref = base.clone()
    # Add high-contrast edge
    ref[:, 10:20, 10:20, :] = 0.9

    injected = apply_edge_aware_texture(base, ref, blend_strength=0.20, filter_radius=2)
    assert injected.shape == base.shape
    assert injected.dtype == base.dtype
    # High frequency edge must be modified
    assert not torch.allclose(injected[:, 10:20, 10:20, :], base[:, 10:20, 10:20, :])
    # Identity when blend_strength is 0
    zero_blend = apply_edge_aware_texture(base, ref, blend_strength=0.0)
    assert torch.equal(zero_blend, base)


def test_color_matching_luminance_and_wavelet():
    gen = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    gen[..., 1] = 0.8  # green
    ref = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    ref[..., 0] = 0.8  # red

    matched_lum = apply_color_matching(ref, gen, mode="luminance")
    assert matched_lum.shape == gen.shape
    assert float(matched_lum[..., 0].mean()) > float(gen[..., 0].mean())

    matched_wav = apply_color_matching(ref, gen, mode="wavelet")
    assert matched_wav.shape == gen.shape


def test_release_gate_registration():
    assert "FiLKrea2TiledDiffusion" in RELEASE_NODES


def test_locales_coverage():
    locales_dir = Path(__file__).resolve().parent.parent / "data" / "locales"
    with open(locales_dir / "en.json", "r", encoding="utf-8") as f:
        en = json.load(f)
    with open(locales_dir / "ru.json", "r", encoding="utf-8") as f:
        ru = json.load(f)

    keys = [
        "krea2_model", "krea2_clip", "krea2_vae", "krea2_image",
        "krea2_prompt", "krea2_seed", "krea2_steps", "krea2_denoise",
        "krea2_tile_grid", "krea2_texture_injection", "krea2_color_match"
    ]
    for k in keys:
        assert k in en, f"Missing {k} in en.json"
        assert k in ru, f"Missing {k} in ru.json"
