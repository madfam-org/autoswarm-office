'use client';

import type { DragEvent } from 'react';
import type { NodeType } from '@selva/shared-types';

interface PaletteItem {
  type: NodeType;
  rfType: string;
  icon: string;
  label: string;
  description: string;
  category: string;
}

const PALETTE_ITEMS: PaletteItem[] = [
  { type: 'agent', rfType: 'agentNode', icon: '🤖', label: 'Agent', description: 'LLM-powered node', category: 'Core' },
  { type: 'human', rfType: 'humanNode', icon: '👤', label: 'Human', description: 'HITL approval gate', category: 'Core' },
  { type: 'passthrough', rfType: 'passthroughNode', icon: '➡️', label: 'Passthrough', description: 'Forward state', category: 'Core' },
  { type: 'subgraph', rfType: 'subgraphNode', icon: '📦', label: 'Subgraph', description: 'Nested workflow', category: 'Compose' },
  { type: 'python_runner', rfType: 'pythonRunnerNode', icon: '🐍', label: 'Python', description: 'Run Python code', category: 'Compute' },
  { type: 'literal', rfType: 'literalNode', icon: '📋', label: 'Literal', description: 'Static value', category: 'Compute' },
  { type: 'loop_counter', rfType: 'loopCounterNode', icon: '🔁', label: 'Loop Counter', description: 'Iteration limit', category: 'Control' },
  { type: 'batch', rfType: 'batchNode', icon: '📦', label: 'Batch', description: 'Parallel processing', category: 'Control' },
];

const CATEGORIES = ['Core', 'Compose', 'Compute', 'Control'];

function onDragStart(event: DragEvent, rfType: string) {
  event.dataTransfer.setData('application/reactflow', rfType);
  event.dataTransfer.effectAllowed = 'move';
}

export function NodePalette() {
  return (
    <div className="w-48 bg-slate-900/80 border-r border-slate-700 overflow-y-auto flex-shrink-0">
      <div className="px-3 py-2 border-b border-slate-700">
        <h3 className="pixel-text text-retro-xs text-slate-400">NODES</h3>
      </div>
      {CATEGORIES.map((cat) => {
        const items = PALETTE_ITEMS.filter((i) => i.category === cat);
        if (items.length === 0) return null;
        return (
          <div key={cat} className="px-2 py-1.5">
            <div className="pixel-text text-retro-xs text-slate-600 mb-1 uppercase">{cat}</div>
            {items.map((item) => (
              <div
                key={item.type}
                draggable
                onDragStart={(e) => onDragStart(e, item.rfType)}
                className="flex items-center gap-2 px-2 py-1.5 rounded cursor-grab hover:bg-slate-800 active:cursor-grabbing transition-colors mb-0.5"
              >
                <span className="text-sm">{item.icon}</span>
                <div className="min-w-0">
                  <div className="pixel-text text-retro-xs text-slate-300 truncate">{item.label}</div>
                  <div className="text-[6px] text-slate-500 truncate">{item.description}</div>
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
