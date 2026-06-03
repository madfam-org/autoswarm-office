import { describe, it, expect } from 'vitest';
import {
  workflowToReactFlow,
  reactFlowToWorkflow,
  workflowToYaml,
  yamlToWorkflow,
  yamlToReactFlow,
  reactFlowToYaml,
} from '../workflow-converter';
import type { WorkflowDefinition, NodeType } from '@selva/shared-types';

function makeWorkflow(nodes: Array<{ id: string; type: NodeType }>, edges: Array<{ source: string; target: string }> = []): WorkflowDefinition {
  return {
    name: 'Test Workflow',
    version: '1.0.0',
    description: 'Test',
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.type,
      label: n.id,
      tools: [],
      interrupt_message: 'Awaiting human approval',
      max_iterations: 5,
      batch_aggregate_strategy: 'collect' as const,
      max_parallel: 5,
      context_policy: { type: 'keep_all' as const, n: 10 },
      thinking_stages: [],
      position_x: 100,
      position_y: 200,
    })),
    edges: edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: '',
      carry_data: true,
    })),
    variables: {},
    entry_node: null,
  };
}

describe('workflow-converter', () => {
  describe('workflowToReactFlow', () => {
    it('converts all 7 node types', () => {
      const types: NodeType[] = ['agent', 'human', 'passthrough', 'subgraph', 'python_runner', 'literal', 'loop_counter'];
      const wf = makeWorkflow(types.map((t) => ({ id: t, type: t })));
      const { nodes } = workflowToReactFlow(wf);

      expect(nodes).toHaveLength(7);
      expect(nodes[0].type).toBe('agentNode');
      expect(nodes[1].type).toBe('humanNode');
      expect(nodes[2].type).toBe('passthroughNode');
      expect(nodes[3].type).toBe('subgraphNode');
      expect(nodes[4].type).toBe('pythonRunnerNode');
      expect(nodes[5].type).toBe('literalNode');
      expect(nodes[6].type).toBe('loopCounterNode');
    });

    it('preserves node positions', () => {
      const wf = makeWorkflow([{ id: 'a', type: 'agent' }]);
      const { nodes } = workflowToReactFlow(wf);
      expect(nodes[0].position).toEqual({ x: 100, y: 200 });
    });

    it('converts edges', () => {
      const wf = makeWorkflow(
        [{ id: 'a', type: 'agent' }, { id: 'b', type: 'human' }],
        [{ source: 'a', target: 'b' }],
      );
      const { edges } = workflowToReactFlow(wf);
      expect(edges).toHaveLength(1);
      expect(edges[0].source).toBe('a');
      expect(edges[0].target).toBe('b');
    });

    it('marks conditional edges as animated', () => {
      const wf = makeWorkflow(
        [{ id: 'a', type: 'agent' }, { id: 'b', type: 'agent' }],
      );
      wf.edges = [{
        source: 'a',
        target: 'b',
        label: 'if approved',
        condition: { regex: 'approved' },
        carry_data: true,
      }];
      const { edges } = workflowToReactFlow(wf);
      expect(edges[0].animated).toBe(true);
      expect(edges[0].type).toBe('conditionalEdge');
    });
  });

  describe('reactFlowToWorkflow', () => {
    it('extracts positions from React Flow nodes', () => {
      const nodes = [{
        id: 'test',
        type: 'agentNode',
        position: { x: 300, y: 400 },
        data: { type: 'agent', label: 'Test', tools: [], interrupt_message: '', max_iterations: 5, context_policy: { type: 'keep_all', n: 10 }, thinking_stages: [] },
      }];
      const wf = reactFlowToWorkflow(nodes, [], { name: 'Test' });
      expect(wf.nodes[0].position_x).toBe(300);
      expect(wf.nodes[0].position_y).toBe(400);
    });
  });

  describe('YAML roundtrip', () => {
    it('roundtrips workflow through YAML', () => {
      const original = makeWorkflow(
        [{ id: 'plan', type: 'agent' }, { id: 'review', type: 'human' }],
        [{ source: 'plan', target: 'review' }],
      );
      const yaml = workflowToYaml(original);
      const parsed = yamlToWorkflow(yaml);

      expect(parsed.name).toBe('Test Workflow');
      expect(parsed.nodes).toHaveLength(2);
      expect(parsed.edges).toHaveLength(1);
      expect(parsed.nodes[0].id).toBe('plan');
      expect(parsed.nodes[0].type).toBe('agent');
      expect(parsed.nodes[1].id).toBe('review');
      expect(parsed.nodes[1].type).toBe('human');
    });

    it('roundtrips through React Flow and back', () => {
      const original = makeWorkflow(
        [{ id: 'a', type: 'agent' }, { id: 'b', type: 'loop_counter' }],
        [{ source: 'a', target: 'b' }],
      );
      const yaml = workflowToYaml(original);
      const { nodes, edges } = yamlToReactFlow(yaml);
      const backYaml = reactFlowToYaml(nodes, edges, { name: original.name });
      const roundtripped = yamlToWorkflow(backYaml);

      expect(roundtripped.name).toBe(original.name);
      expect(roundtripped.nodes).toHaveLength(2);
      expect(roundtripped.edges).toHaveLength(1);
    });

    it('preserves defaults for missing fields', () => {
      const minimal = `
name: Minimal
nodes:
  - id: n1
    type: agent
`;
      const wf = yamlToWorkflow(minimal);
      expect(wf.nodes[0].tools).toEqual([]);
      expect(wf.nodes[0].max_iterations).toBe(5);
      expect(wf.nodes[0].context_policy.type).toBe('keep_all');
    });
  });
});
