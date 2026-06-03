/**
 * Converts between YAML workflow definitions and React Flow nodes/edges.
 */

import yaml from 'js-yaml';
import type { Node, Edge } from '@xyflow/react';
import type {
  WorkflowDefinition,
  NodeDefinition,
  EdgeDefinition,
  NodeType,
  createDefaultNode,
  createDefaultEdge,
} from '@selva/shared-types';

/** Default grid spacing for new nodes */
const GRID_OFFSET_X = 200;
const GRID_OFFSET_Y = 120;

/** Map NodeType → React Flow custom node type key */
const NODE_TYPE_MAP: Record<NodeType, string> = {
  agent: 'agentNode',
  batch: 'batchNode',
  human: 'humanNode',
  passthrough: 'passthroughNode',
  subgraph: 'subgraphNode',
  python_runner: 'pythonRunnerNode',
  literal: 'literalNode',
  loop_counter: 'loopCounterNode',
};

/** Reverse map: React Flow type key → NodeType */
const REVERSE_NODE_TYPE_MAP: Record<string, NodeType> = Object.fromEntries(
  Object.entries(NODE_TYPE_MAP).map(([k, v]) => [v, k as NodeType]),
);

/**
 * Convert a WorkflowDefinition to React Flow nodes and edges.
 */
export function workflowToReactFlow(workflow: WorkflowDefinition): {
  nodes: Node[];
  edges: Edge[];
} {
  const nodes: Node[] = workflow.nodes.map((node, index) => ({
    id: node.id,
    type: NODE_TYPE_MAP[node.type] ?? 'agentNode',
    position: {
      x: node.position_x || (index % 4) * GRID_OFFSET_X + 100,
      y: node.position_y || Math.floor(index / 4) * GRID_OFFSET_Y + 100,
    },
    data: { ...node },
  }));

  const edges: Edge[] = workflow.edges.map((edge, index) => ({
    id: `e-${edge.source}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    label: edge.label || undefined,
    type: edge.condition ? 'conditionalEdge' : 'default',
    data: {
      condition: edge.condition ?? null,
      carry_data: edge.carry_data,
      transform: edge.transform ?? null,
    },
    animated: !!edge.condition,
  }));

  return { nodes, edges };
}

/**
 * Convert React Flow nodes/edges back to a WorkflowDefinition.
 */
export function reactFlowToWorkflow(
  nodes: Node[],
  edges: Edge[],
  meta: { name: string; version?: string; description?: string; variables?: Record<string, unknown>; entry_node?: string | null },
): WorkflowDefinition {
  const workflowNodes: NodeDefinition[] = nodes.map((node) => {
    const data = node.data as Partial<NodeDefinition>;
    const nodeType = REVERSE_NODE_TYPE_MAP[node.type ?? ''] ?? (data.type as NodeType) ?? 'agent';

    return {
      id: node.id,
      type: nodeType,
      label: (data.label as string) ?? '',
      model: data.model ?? null,
      system_prompt: data.system_prompt ?? null,
      tools: (data.tools as string[]) ?? [],
      temperature: data.temperature ?? null,
      interrupt_message: (data.interrupt_message as string) ?? 'Awaiting human approval',
      subgraph_id: data.subgraph_id ?? null,
      code: data.code ?? null,
      literal_value: data.literal_value ?? null,
      max_iterations: (data.max_iterations as number) ?? 5,
      batch_split_key: data.batch_split_key ?? null,
      batch_aggregate_strategy: data.batch_aggregate_strategy ?? 'collect',
      max_parallel: (data.max_parallel as number) ?? 5,
      delegate_node_id: data.delegate_node_id ?? null,
      context_policy: data.context_policy ?? { type: 'keep_all', n: 10 },
      thinking_stages: (data.thinking_stages as string[]) ?? [],
      position_x: node.position.x,
      position_y: node.position.y,
    } as NodeDefinition;
  });

  const workflowEdges: EdgeDefinition[] = edges.map((edge) => {
    const data = edge.data as Record<string, unknown> | undefined;
    return {
      source: edge.source,
      target: edge.target,
      label: (edge.label as string) ?? '',
      condition: (data?.condition as EdgeDefinition['condition']) ?? null,
      carry_data: (data?.carry_data as boolean) ?? true,
      transform: (data?.transform as string) ?? null,
    };
  });

  return {
    name: meta.name,
    version: meta.version ?? '1.0.0',
    description: meta.description ?? '',
    nodes: workflowNodes,
    edges: workflowEdges,
    variables: meta.variables ?? {},
    entry_node: meta.entry_node ?? null,
  };
}

/**
 * Parse YAML string to WorkflowDefinition.
 */
export function yamlToWorkflow(yamlStr: string): WorkflowDefinition {
  const raw = yaml.load(yamlStr) as WorkflowDefinition;
  // Ensure required defaults
  return {
    name: raw.name ?? 'Untitled',
    version: raw.version ?? '1.0.0',
    description: raw.description ?? '',
    nodes: (raw.nodes ?? []).map((n) => ({
      ...n,
      tools: n.tools ?? [],
      interrupt_message: n.interrupt_message ?? 'Awaiting human approval',
      max_iterations: n.max_iterations ?? 5,
      context_policy: n.context_policy ?? { type: 'keep_all', n: 10 },
      thinking_stages: n.thinking_stages ?? [],
      position_x: n.position_x ?? 0,
      position_y: n.position_y ?? 0,
    })),
    edges: (raw.edges ?? []).map((e) => ({
      ...e,
      label: e.label ?? '',
      carry_data: e.carry_data ?? true,
    })),
    variables: raw.variables ?? {},
    entry_node: raw.entry_node ?? null,
  };
}

/**
 * Serialize WorkflowDefinition to YAML string.
 */
export function workflowToYaml(wf: WorkflowDefinition): string {
  return yaml.dump(wf, { noRefs: true, lineWidth: 120, sortKeys: false });
}

/**
 * Full roundtrip: YAML → React Flow nodes/edges.
 */
export function yamlToReactFlow(yamlStr: string): { nodes: Node[]; edges: Edge[] } {
  return workflowToReactFlow(yamlToWorkflow(yamlStr));
}

/**
 * Full roundtrip: React Flow → YAML string.
 */
export function reactFlowToYaml(
  nodes: Node[],
  edges: Edge[],
  meta: { name: string; version?: string; description?: string },
): string {
  return workflowToYaml(reactFlowToWorkflow(nodes, edges, meta));
}
