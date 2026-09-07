"""Frontend contract for `FiLKrea2TiledDiffusion`."""

from __future__ import annotations

from ..widgets import _combo, _float, _int, _slider, _string
from ..schema import NodeContract, NodeInputs, NodeOutput
from ...brand import CATEGORY_IMAGE
TILE_GRIDS = ["1x1", "1x2", "2x1", "2x2", "2x3", "3x2", "3x3", "4x4"]
ALL_TILE_GRIDS = ["auto"] + TILE_GRIDS
TILE_OVERLAP_OPTIONS = ["auto (256px)", "128px", "192px", "256px", "384px", "512px"]
COLOR_MATCH_OPTIONS = ["none", "luminance", "wavelet"]

CONTRACT = NodeContract(
    id="FiLKrea2TiledDiffusion",
    title="📐 Krea 2 Tiled Diffusion",
    category=CATEGORY_IMAGE,
    description="Ultra-high-definition tiled upscale with RoPE canvas coordinates, edge-aware adaptive texture and color matching.",
    min_size=(320, 560),
    family="image",
    inputs=NodeInputs(
        required=[
            _string("prompt", default="hyperrealistic, highly detailed, 8k uhd", label="Prompt"),
            _int("seed", default=0, minv=0, maxv=0xFFFFFFFFFFFFFFFF, step=1, label="Seed"),
            _int("steps", default=8, minv=1, maxv=50, step=1, label="Steps"),
            _slider("denoise", default=0.22, minv=0.0, maxv=1.0, step=0.01, label="Denoise"),
            _float("vision_weight", default=1.40, minv=0.0, maxv=3.0, step=0.05, label="Vision weight"),
            _slider("upscale_factor", default=2.0, minv=1.0, maxv=8.0, step=0.1, label="Upscale factor"),
            _combo("tile_grid", values=ALL_TILE_GRIDS, default="auto", label="Tile grid"),
            _combo("tile_overlap", values=TILE_OVERLAP_OPTIONS, default="auto (256px)", label="Tile overlap"),
            _int("tile_batch_size", default=1, minv=1, maxv=8, step=1, label="Tile batch size"),
            _slider("texture_injection", default=0.20, minv=0.0, maxv=1.0, step=0.02, label="Texture injection"),
            _combo("color_match", values=COLOR_MATCH_OPTIONS, default="none", label="Color match"),
            _combo("identity_lora_name", values=["none"], default="none", label="Identity LoRA"),
            _float("identity_lora_strength", default=1.0, minv=0.0, maxv=2.0, step=0.05, label="LoRA strength"),
        ],
        optional=[],
    ),
    outputs=[
        NodeOutput(name="image", type="IMAGE"),
        NodeOutput(name="latent", type="LATENT"),
    ],
)
