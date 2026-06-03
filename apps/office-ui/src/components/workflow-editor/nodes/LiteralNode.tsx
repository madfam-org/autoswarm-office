import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import type { NodeDefinition } from '@selva/shared-types';

export function LiteralNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as NodeDefinition;
  let preview = 'null';
  try {
    preview = JSON.stringify(nodeData.literal_value) ?? 'null';
    if (preview.length > 40) preview = preview.slice(0, 37) + '...';
  } catch {
    preview = String(nodeData.literal_value);
  }
  return (
    <div className={`retro-panel pixel-border min-w-[160px] bg-slate-800/95 shadow-pixelact-raised ${selected ? 'ring-2 ring-cyan-400' : ''}`}>
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-pixelact-border bg-cyan-500/20">
        <span>📋</span>
        <span className="pixel-text text-retro-xs truncate">{nodeData.label || nodeData.id}</span>
      </div>
      <div className="px-2 py-1.5 text-retro-xs text-slate-400 truncate font-mono">
        {preview}
      </div>
      <Handle type="target" position={Position.Top} className="!bg-cyan-400 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !w-2.5 !h-2.5" />
    </div>
  );
}
