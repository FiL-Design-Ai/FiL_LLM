import { describe, it, expect, vi } from "vitest";
import { showAnyNode } from "@/nodes2/nodes/show_any";
import type { LGraphNode } from "@/types/comfy";

vi.mock("@/nodes2/domWidgetHost", () => ({
  addFilDomWidget: () => ({ name: "fil_show_any_view", state: {} }),
  unmountAllFilWidgets: () => {},
}));

vi.mock("@/nodes2/widgetInputSockets", () => ({
  exposeWidgetInputSockets: () => {},
  installWidgetSocketSync: () => {},
}));

vi.mock("@/nodes2/applyFxComposables", () => ({
  applyFxComposables: () => {},
}));

function createMockShowAnyNode() {
  const nodeType = {
    prototype: {
      findInputSlot(type: string, free?: boolean) {
        const self = this as { inputs?: Array<{ type: string; link: number | null }> };
        return self.inputs?.findIndex((i) => i.type === type && (!free || i.link == null)) ?? -1;
      },
    },
  } as { prototype: Record<string, unknown> };
  showAnyNode.register(nodeType as never, { name: "FiLShowAny" } as never);

  const mockNode: Partial<LGraphNode> & {
    inputs: Array<{ name: string; type: string; link: number | null }>;
    outputs: Array<{ name: string; type: string; label?: string }>;
    graph: { links: Record<number, unknown>; getNodeById?: () => unknown; setDirtyCanvas?: () => void };
    connect: ReturnType<typeof vi.fn>;
  } = {
    inputs: [
      { name: "source", type: "*", link: null },
      { name: "text", type: "STRING", link: null },
    ],
    outputs: [{ name: "*", type: "*", label: "*" }],
    widgets: [{ name: "text", value: "" }] as never,
    graph: { links: {}, setDirtyCanvas: vi.fn() },
    connect: vi.fn((_slot, _targetNode, _targetSlot) => true),
  };

  Object.setPrototypeOf(mockNode, nodeType.prototype);
  (nodeType.prototype.onNodeCreated as (this: unknown) => unknown).call(mockNode);

  return { node: mockNode as unknown as LGraphNode, proto: nodeType.prototype };
}

describe("show_any.ts — source slot auto-connection prioritization", () => {
  it("prioritizes source input for findInputByType even when connecting STRING type", () => {
    const { node } = createMockShowAnyNode();
    const result = (node as unknown as { findInputByType: (type: string) => { index: number; slot: { name: string } } }).findInputByType("STRING");

    expect(result).toBeDefined();
    expect(result?.index).toBe(0);
    expect(result?.slot.name).toBe("source");
  });

  it("prioritizes source input for findInputSlot even when connecting STRING type", () => {
    const { node } = createMockShowAnyNode();
    const slotIdx = (node as unknown as { findInputSlot: (type: string, free?: boolean) => number }).findInputSlot("STRING", true);

    expect(slotIdx).toBe(0);
  });

  it("prioritizes source input for findSlotByType", () => {
    const { node } = createMockShowAnyNode();
    const slotIdx = (node as unknown as { findSlotByType: (isInput: boolean, type: string) => number }).findSlotByType(true, "STRING");

    expect(slotIdx).toBe(0);
  });

  it("connectByType connects directly to source (slot 0)", () => {
    const { node } = createMockShowAnyNode();
    const sourceNode = {} as LGraphNode;
    (node as unknown as { connectByType: (slot: number, src: LGraphNode, type: string) => boolean }).connectByType(0, sourceNode, "STRING");

    expect(node.connect).toHaveBeenCalledWith(0, sourceNode, 0);
  });

  it("falls back to standard behavior when source slot is already occupied", () => {
    const { node } = createMockShowAnyNode();
    // Occupy source slot with link 1
    node.inputs![0].link = 1;

    // Now findInputSlot for STRING should fall back and locate text (slot 1)
    const slotIdx = (node as unknown as { findInputSlot: (type: string, free?: boolean) => number }).findInputSlot("STRING", true);
    expect(slotIdx).toBe(1);
  });
});
