'use client';

import { useState, useCallback, useEffect, useRef, useMemo, type DragEvent } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
} from '@xyflow/react';
import { gameEventBus } from '@/game/PhaserGame';
import { EVENT_CHAT_FOCUS } from '@/lib/constants';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useWorkflow } from '@/hooks/useWorkflow';
import { useExecutionLog } from '@/hooks/useExecutionLog';
import { useTaskDispatch } from '@/hooks/useTaskDispatch';
import {
  workflowToReactFlow,
  reactFlowToWorkflow,
  yamlToWorkflow,
  workflowToYaml,
  yamlToReactFlow,
} from '@/lib/workflow-converter';
import { createDefaultNode, type NodeDefinition } from '@selva/shared-types';
import type { OfficeState } from '@selva/shared-types';

import { nodeTypes } from './nodes';
import { edgeTypes } from './edges';
import { NodePalette } from './NodePalette';
import { PropertiesPanel } from './PropertiesPanel';
import { EditorToolbar } from './EditorToolbar';
import { ExecutionLog } from './ExecutionLog';
import { TemplateGallery } from './TemplateGallery';

interface WorkflowEditorProps {
  open: boolean;
  onClose: () => void;
  officeState?: OfficeState | null;
}

const RF_TYPE_TO_NODE_TYPE: Record<string, string> = {
  agentNode: 'agent',
  batchNode: 'batch',
  humanNode: 'human',
  passthroughNode: 'passthrough',
  subgraphNode: 'subgraph',
  pythonRunnerNode: 'python_runner',
  literalNode: 'literal',
  loopCounterNode: 'loop_counter',
};

let nodeIdCounter = 0;

function InnerEditor({ onClose, officeState }: Omit<WorkflowEditorProps, 'open'>) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [workflowName, setWorkflowName] = useState('Untitled Workflow');
  const [templateGalleryOpen, setTemplateGalleryOpen] = useState(false);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const {
    status,
    error,
    workflowList,
    workflow,
    validationResult,
    loadList,
    load,
    save,
    validate,
    importYaml,
    exportYaml,
  } = useWorkflow();

  const { events, clearEvents } = useExecutionLog(officeState ?? null);
  const { dispatch: dispatchTask } = useTaskDispatch();

  // Load workflow list on mount
  useEffect(() => {
    loadList();
  }, [loadList]);

  // Derive active node from office state
  const activeNodeId = useMemo(() => {
    if (!officeState?.departments) return null;
    for (const dept of officeState.departments) {
      if (!dept.agents) continue;
      for (const agent of dept.agents) {
        const nid = (agent as unknown as Record<string, unknown>).currentNodeId as string | undefined;
        if (nid) return nid;
      }
    }
    return null;
  }, [officeState]);

  // Apply active node highlighting
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        className: n.id === activeNodeId
          ? 'ring-2 ring-cyan-400 animate-pulse-border rounded'
          : '',
      })),
    );
  }, [activeNodeId, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            type: 'default',
            data: { condition: null, carry_data: true, transform: null },
          },
          eds,
        ),
      );
    },
    [setEdges],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
      setSelectedEdge(null);
    },
    [],
  );

  const onEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      setSelectedEdge(edge);
      setSelectedNode(null);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
  }, []);

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const rfType = event.dataTransfer.getData('application/reactflow');
      if (!rfType || !reactFlowWrapper.current) return;

      const nodeType = RF_TYPE_TO_NODE_TYPE[rfType];
      if (!nodeType) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      };

      const id = `${nodeType}_${++nodeIdCounter}`;
      const defaultData = createDefaultNode(nodeType as NodeDefinition['type'], id);

      const newNode: Node = {
        id,
        type: rfType,
        position,
        data: { ...defaultData },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [setNodes],
  );

  // Node property updates
  const onNodeUpdate = useCallback(
    (id: string, data: Partial<NodeDefinition>) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== id) return n;
          return { ...n, data: { ...n.data, ...data } };
        }),
      );
      // Update selected node reference
      setSelectedNode((prev) => {
        if (prev?.id !== id) return prev;
        return { ...prev, data: { ...prev.data, ...data } };
      });
    },
    [setNodes],
  );

  // Edge property updates
  const onEdgeUpdate = useCallback(
    (id: string, data: Record<string, unknown>) => {
      setEdges((eds) =>
        eds.map((e) => {
          if (e.id !== id) return e;
          const newData = { ...(e.data as Record<string, unknown>), ...data };
          return {
            ...e,
            data: newData,
            label: data.label !== undefined ? data.label as string : e.label,
            type: newData.condition ? 'conditionalEdge' : 'default',
            animated: !!newData.condition,
          };
        }),
      );
      setSelectedEdge((prev) => {
        if (prev?.id !== id) return prev;
        const newData = { ...(prev.data as Record<string, unknown>), ...data };
        return {
          ...prev,
          data: newData,
          label: data.label !== undefined ? data.label as string : prev.label,
        };
      });
    },
    [setEdges],
  );

  // Toolbar actions
  const handleNew = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setWorkflowName('Untitled Workflow');
    setSelectedNode(null);
    setSelectedEdge(null);
  }, [setNodes, setEdges]);

  const handleSave = useCallback(async () => {
    const wf = reactFlowToWorkflow(nodes, edges, { name: workflowName });
    const yamlStr = workflowToYaml(wf);
    const result = await save(workflowName, yamlStr, workflow?.id);
    if (result) {
      await loadList();
    }
  }, [nodes, edges, workflowName, workflow?.id, save, loadList]);

  const handleLoad = useCallback(
    async (id: string) => {
      const loaded = await load(id);
      if (loaded) {
        setWorkflowName(loaded.name);
        const wf = yamlToWorkflow(loaded.yaml_content);
        const { nodes: rfNodes, edges: rfEdges } = workflowToReactFlow(wf);
        setNodes(rfNodes);
        setEdges(rfEdges);
      }
    },
    [load, setNodes, setEdges],
  );

  const handleExport = useCallback(() => {
    const wf = reactFlowToWorkflow(nodes, edges, { name: workflowName });
    const yamlStr = workflowToYaml(wf);
    const blob = new Blob([yamlStr], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${workflowName.replace(/\s+/g, '-').toLowerCase()}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  }, [nodes, edges, workflowName]);

  const handleImport = useCallback(
    (yamlStr: string) => {
      try {
        const { nodes: rfNodes, edges: rfEdges } = yamlToReactFlow(yamlStr);
        const wf = yamlToWorkflow(yamlStr);
        setNodes(rfNodes);
        setEdges(rfEdges);
        setWorkflowName(wf.name);
      } catch {
        // If parse fails, show error
      }
    },
    [setNodes, setEdges],
  );

  const handleValidate = useCallback(() => {
    const wf = reactFlowToWorkflow(nodes, edges, { name: workflowName });
    const yamlStr = workflowToYaml(wf);
    validate(yamlStr);
  }, [nodes, edges, workflowName, validate]);

  const handleRun = useCallback(async () => {
    if (!workflow?.id) {
      // Save first
      const wf = reactFlowToWorkflow(nodes, edges, { name: workflowName });
      const yamlStr = workflowToYaml(wf);
      const result = await save(workflowName, yamlStr, workflow?.id);
      if (!result) return;
      await dispatchTask({
        description: `Run workflow: ${workflowName}`,
        graph_type: 'custom',
        workflow_id: result.id,
      });
    } else {
      await dispatchTask({
        description: `Run workflow: ${workflowName}`,
        graph_type: 'custom',
        workflow_id: workflow.id,
      });
    }
  }, [workflow, nodes, edges, workflowName, save, dispatchTask]);

  const handleTemplateCreated = useCallback(
    (created: { id: string; name: string; yaml_content: string }) => {
      setWorkflowName(created.name);
      try {
        const wf = yamlToWorkflow(created.yaml_content);
        const { nodes: rfNodes, edges: rfEdges } = workflowToReactFlow(wf);
        setNodes(rfNodes);
        setEdges(rfEdges);
      } catch {
        // Best-effort load; canvas stays empty if parse fails
      }
      // Refresh the workflow list to include the new entry
      loadList();
    },
    [setNodes, setEdges, loadList],
  );

  return (
    <div className="flex flex-col w-full h-full">
      <EditorToolbar
        workflowName={workflowName}
        onNameChange={setWorkflowName}
        workflowList={workflowList}
        currentWorkflowId={workflow?.id ?? null}
        status={status}
        validationResult={validationResult}
        onNew={handleNew}
        onSave={handleSave}
        onLoad={handleLoad}
        onExport={handleExport}
        onImport={handleImport}
        onValidate={handleValidate}
        onRun={handleRun}
        onClose={onClose}
        onOpenTemplates={() => setTemplateGalleryOpen(true)}
      />

      <div className="flex flex-1 min-h-0">
        <NodePalette />

        <div ref={reactFlowWrapper} className="flex-1 workflow-editor">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            onDragOver={onDragOver}
            onDrop={onDrop}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            snapToGrid
            snapGrid={[16, 16]}
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#334155" />
            <Controls className="!bg-slate-800 !border-slate-600 !shadow-pixelact-raised" />
            <MiniMap
              className="!bg-slate-900 !border-slate-600"
              nodeColor={() => '#6366f1'}
              maskColor="rgba(15, 23, 42, 0.7)"
            />
          </ReactFlow>
        </div>

        <PropertiesPanel
          selectedNode={selectedNode}
          selectedEdge={selectedEdge}
          onNodeUpdate={onNodeUpdate}
          onEdgeUpdate={onEdgeUpdate}
          workflowList={workflowList}
        />
      </div>

      <ExecutionLog events={events} onClear={clearEvents} />

      <TemplateGallery
        open={templateGalleryOpen}
        onClose={() => setTemplateGalleryOpen(false)}
        onCreated={handleTemplateCreated}
      />
    </div>
  );
}

export function WorkflowEditor({ open, onClose, officeState }: WorkflowEditorProps) {
  const trapRef = useFocusTrap(open);

  // Suppress game input while editor is open
  useEffect(() => {
    if (open) {
      gameEventBus.emit(EVENT_CHAT_FOCUS, true);
      return () => {
        gameEventBus.emit(EVENT_CHAT_FOCUS, false);
      };
    }
  }, [open]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-modal animate-fade-in" role="dialog" aria-modal="true" aria-label="Workflow Editor">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/80" onClick={onClose} />

      {/* Editor container */}
      <div
        ref={trapRef as React.RefObject<HTMLDivElement>}
        className="absolute inset-4 sm:inset-6 lg:inset-8 retro-panel pixel-border-accent animate-pop-in flex flex-col overflow-hidden"
      >
        <ReactFlowProvider>
          <InnerEditor onClose={onClose} officeState={officeState} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
