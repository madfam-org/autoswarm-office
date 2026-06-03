'use client';

import { useCallback } from 'react';
import type { Node, Edge } from '@xyflow/react';
import type { NodeDefinition, NodeType, ContextWindowPolicy } from '@selva/shared-types';
import type { WorkflowSummary } from '@/hooks/useWorkflow';

interface PropertiesPanelProps {
  selectedNode: Node | null;
  selectedEdge: Edge | null;
  onNodeUpdate: (id: string, data: Partial<NodeDefinition>) => void;
  onEdgeUpdate: (id: string, data: Record<string, unknown>) => void;
  workflowList: WorkflowSummary[];
}

const CONTEXT_POLICIES: ContextWindowPolicy[] = ['keep_all', 'keep_last_n', 'clear_all', 'sliding_window'];

const NODE_TYPE_REVERSE: Record<string, NodeType> = {
  agentNode: 'agent',
  batchNode: 'batch',
  humanNode: 'human',
  passthroughNode: 'passthrough',
  subgraphNode: 'subgraph',
  pythonRunnerNode: 'python_runner',
  literalNode: 'literal',
  loopCounterNode: 'loop_counter',
};

export function PropertiesPanel({
  selectedNode,
  selectedEdge,
  onNodeUpdate,
  onEdgeUpdate,
  workflowList,
}: PropertiesPanelProps) {
  const nodeData = selectedNode?.data as NodeDefinition | undefined;
  const nodeType = selectedNode ? (NODE_TYPE_REVERSE[selectedNode.type ?? ''] ?? nodeData?.type) : null;

  const updateField = useCallback(
    (field: string, value: unknown) => {
      if (selectedNode) {
        onNodeUpdate(selectedNode.id, { [field]: value });
      }
    },
    [selectedNode, onNodeUpdate],
  );

  const updateEdge = useCallback(
    (field: string, value: unknown) => {
      if (selectedEdge) {
        onEdgeUpdate(selectedEdge.id, { [field]: value });
      }
    },
    [selectedEdge, onEdgeUpdate],
  );

  if (!selectedNode && !selectedEdge) {
    return (
      <div className="w-72 bg-slate-900/80 border-l border-slate-700 flex-shrink-0 flex items-center justify-center">
        <p className="pixel-text text-retro-xs text-slate-600 text-center px-4">
          Select a node or edge to edit
        </p>
      </div>
    );
  }

  if (selectedEdge) {
    const edgeData = selectedEdge.data as Record<string, unknown> | undefined;
    const condition = edgeData?.condition as Record<string, string> | null;
    return (
      <div className="w-72 bg-slate-900/80 border-l border-slate-700 flex-shrink-0 overflow-y-auto">
        <div className="px-3 py-2 border-b border-slate-700">
          <h3 className="pixel-text text-retro-xs text-slate-400">EDGE</h3>
        </div>
        <div className="p-3 space-y-3">
          <Field label="Label">
            <input
              className="pxa-input w-full"
              value={(selectedEdge.label as string) ?? ''}
              onChange={(e) => updateEdge('label', e.target.value)}
            />
          </Field>
          <Field label="Condition Type">
            <select
              className="pxa-input w-full"
              value={condition?.regex ? 'regex' : condition?.keyword ? 'keyword' : condition?.expression ? 'expression' : 'none'}
              onChange={(e) => {
                const type = e.target.value;
                if (type === 'none') {
                  updateEdge('condition', null);
                } else {
                  updateEdge('condition', { [type]: '' });
                }
              }}
            >
              <option value="none">None</option>
              <option value="regex">Regex</option>
              <option value="keyword">Keyword</option>
              <option value="expression">Expression</option>
            </select>
          </Field>
          {condition && (
            <Field label="Pattern">
              <input
                className="pxa-input w-full"
                value={condition.regex ?? condition.keyword ?? condition.expression ?? ''}
                onChange={(e) => {
                  const key = condition.regex != null ? 'regex' : condition.keyword != null ? 'keyword' : 'expression';
                  updateEdge('condition', { [key]: e.target.value });
                }}
              />
            </Field>
          )}
          <Field label="Carry Data">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={(edgeData?.carry_data as boolean) ?? true}
                onChange={(e) => updateEdge('carry_data', e.target.checked)}
              />
              <span className="text-retro-xs text-slate-400">Pass state along edge</span>
            </label>
          </Field>
        </div>
      </div>
    );
  }

  return (
    <div className="w-72 bg-slate-900/80 border-l border-slate-700 flex-shrink-0 overflow-y-auto">
      <div className="px-3 py-2 border-b border-slate-700">
        <h3 className="pixel-text text-retro-xs text-slate-400">
          {(nodeType ?? 'node').toUpperCase()}
        </h3>
      </div>
      <div className="p-3 space-y-3">
        <Field label="ID">
          <input className="pxa-input w-full opacity-60" value={selectedNode!.id} readOnly />
        </Field>
        <Field label="Label">
          <input
            className="pxa-input w-full"
            value={nodeData?.label ?? ''}
            onChange={(e) => updateField('label', e.target.value)}
          />
        </Field>

        {/* Agent-specific fields */}
        {nodeType === 'agent' && (
          <>
            <Field label="Model">
              <input
                className="pxa-input w-full"
                value={nodeData?.model ?? ''}
                placeholder="e.g. gpt-4o"
                onChange={(e) => updateField('model', e.target.value || null)}
              />
            </Field>
            <Field label="System Prompt">
              <textarea
                className="pxa-input w-full h-20 resize-y font-mono"
                value={nodeData?.system_prompt ?? ''}
                onChange={(e) => updateField('system_prompt', e.target.value || null)}
              />
            </Field>
            <Field label="Tools (comma-separated)">
              <input
                className="pxa-input w-full"
                value={nodeData?.tools?.join(', ') ?? ''}
                onChange={(e) =>
                  updateField(
                    'tools',
                    e.target.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  )
                }
              />
            </Field>
            <Field label="Temperature">
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={nodeData?.temperature ?? 0.7}
                  onChange={(e) => updateField('temperature', parseFloat(e.target.value))}
                  className="flex-1"
                />
                <span className="text-retro-xs text-slate-400 w-8 text-right">
                  {(nodeData?.temperature ?? 0.7).toFixed(1)}
                </span>
              </div>
            </Field>
          </>
        )}

        {/* Human-specific fields */}
        {nodeType === 'human' && (
          <Field label="Interrupt Message">
            <textarea
              className="pxa-input w-full h-16 resize-y"
              value={nodeData?.interrupt_message ?? ''}
              onChange={(e) => updateField('interrupt_message', e.target.value)}
            />
          </Field>
        )}

        {/* Subgraph-specific fields */}
        {nodeType === 'subgraph' && (
          <Field label="Subgraph Workflow">
            <select
              className="pxa-input w-full"
              value={nodeData?.subgraph_id ?? ''}
              onChange={(e) => updateField('subgraph_id', e.target.value || null)}
            >
              <option value="">Select workflow...</option>
              {workflowList.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        {/* Python runner fields */}
        {nodeType === 'python_runner' && (
          <Field label="Python Code">
            <textarea
              className="pxa-input w-full h-28 resize-y font-mono text-[7px]"
              value={nodeData?.code ?? ''}
              onChange={(e) => updateField('code', e.target.value || null)}
            />
          </Field>
        )}

        {/* Literal fields */}
        {nodeType === 'literal' && (
          <Field label="Value (JSON)">
            <textarea
              className="pxa-input w-full h-16 resize-y font-mono text-[7px]"
              value={nodeData?.literal_value != null ? JSON.stringify(nodeData.literal_value, null, 2) : ''}
              onChange={(e) => {
                try {
                  updateField('literal_value', JSON.parse(e.target.value));
                } catch {
                  // Allow invalid intermediate JSON while typing
                }
              }}
            />
          </Field>
        )}

        {/* Loop counter fields */}
        {nodeType === 'loop_counter' && (
          <Field label="Max Iterations">
            <input
              type="number"
              className="pxa-input w-full"
              min={1}
              max={100}
              value={nodeData?.max_iterations ?? 5}
              onChange={(e) => updateField('max_iterations', parseInt(e.target.value) || 5)}
            />
          </Field>
        )}

        {/* Batch node fields */}
        {nodeType === 'batch' && (
          <>
            <Field label="Split Key">
              <input
                className="pxa-input w-full"
                value={nodeData?.batch_split_key ?? ''}
                placeholder="e.g. items"
                onChange={(e) => updateField('batch_split_key', e.target.value || null)}
              />
            </Field>
            <Field label="Delegate Node ID">
              <input
                className="pxa-input w-full"
                value={nodeData?.delegate_node_id ?? ''}
                placeholder="e.g. worker_node"
                onChange={(e) => updateField('delegate_node_id', e.target.value || null)}
              />
            </Field>
            <Field label="Aggregate Strategy">
              <select
                className="pxa-input w-full"
                value={nodeData?.batch_aggregate_strategy ?? 'collect'}
                onChange={(e) => updateField('batch_aggregate_strategy', e.target.value)}
              >
                <option value="collect">Collect</option>
                <option value="merge">Merge</option>
                <option value="vote">Vote</option>
              </select>
            </Field>
            <Field label="Max Parallel">
              <input
                type="number"
                className="pxa-input w-full"
                min={1}
                max={50}
                value={nodeData?.max_parallel ?? 5}
                onChange={(e) => updateField('max_parallel', parseInt(e.target.value) || 5)}
              />
            </Field>
          </>
        )}

        {/* Context policy (all nodes) */}
        <Field label="Context Policy">
          <select
            className="pxa-input w-full"
            value={nodeData?.context_policy?.type ?? 'keep_all'}
            onChange={(e) =>
              updateField('context_policy', {
                type: e.target.value,
                n: nodeData?.context_policy?.n ?? 10,
              })
            }
          >
            {CONTEXT_POLICIES.map((p) => (
              <option key={p} value={p}>
                {p.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </Field>
        {(nodeData?.context_policy?.type === 'keep_last_n' ||
          nodeData?.context_policy?.type === 'sliding_window') && (
          <Field label="N (messages)">
            <input
              type="number"
              className="pxa-input w-full"
              min={1}
              value={nodeData?.context_policy?.n ?? 10}
              onChange={(e) =>
                updateField('context_policy', {
                  type: nodeData?.context_policy?.type ?? 'keep_last_n',
                  n: parseInt(e.target.value) || 10,
                })
              }
            />
          </Field>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block pixel-text text-[6px] text-slate-500 mb-1 uppercase">{label}</label>
      {children}
    </div>
  );
}
