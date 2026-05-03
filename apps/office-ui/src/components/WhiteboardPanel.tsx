'use client';

import { type FC, useRef, useEffect, useCallback, useState } from 'react';
import type { WhiteboardStroke, WhiteboardTool } from '@/hooks/useWhiteboard';
import { useFocusTrap } from '@/hooks/useFocusTrap';

interface WhiteboardPanelProps {
  open: boolean;
  onClose: () => void;
  strokes: WhiteboardStroke[];
  tool: WhiteboardTool;
  color: string;
  width: number;
  colors: readonly string[];
  widths: readonly number[];
  onSendStroke: (x: number, y: number, toX: number, toY: number) => void;
  onClear: () => void;
  onToolChange: (tool: WhiteboardTool) => void;
  onColorChange: (color: string) => void;
  onWidthChange: (width: number) => void;
}

const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 600;

export const WhiteboardPanel: FC<WhiteboardPanelProps> = ({
  open,
  onClose,
  strokes,
  tool,
  color,
  width,
  colors,
  widths,
  onSendStroke,
  onClear,
  onToolChange,
  onColorChange,
  onWidthChange,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);

  // Redraw all strokes whenever the strokes array changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    for (const stroke of strokes) {
      ctx.beginPath();
      ctx.moveTo(stroke.x, stroke.y);
      ctx.lineTo(stroke.toX, stroke.toY);
      ctx.strokeStyle = stroke.tool === 'eraser' ? '#0f172a' : stroke.color;
      ctx.lineWidth = stroke.width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
  }, [strokes]);

  const getCanvasPos = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return {
        x: ((e.clientX - rect.left) / rect.width) * CANVAS_WIDTH,
        y: ((e.clientY - rect.top) / rect.height) * CANVAS_HEIGHT,
      };
    },
    [],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      e.preventDefault();
      setIsDrawing(true);
      const pos = getCanvasPos(e);
      lastPosRef.current = pos;
      (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    },
    [getCanvasPos],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!isDrawing || !lastPosRef.current) return;
      const pos = getCanvasPos(e);
      onSendStroke(lastPosRef.current.x, lastPosRef.current.y, pos.x, pos.y);
      lastPosRef.current = pos;
    },
    [isDrawing, getCanvasPos, onSendStroke],
  );

  const handlePointerUp = useCallback(() => {
    setIsDrawing(false);
    lastPosRef.current = null;
  }, []);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  const focusTrapRef = useFocusTrap<HTMLDivElement>(open);

  if (!open) return null;

  return (
    <div
      ref={focusTrapRef}
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/70"
      role="dialog"
      aria-modal="true"
      aria-labelledby="whiteboard-title"
    >
      <div className="retro-panel pixel-border-accent bg-slate-900/95 p-4 flex flex-col gap-3 max-w-[900px] w-full mx-4 animate-pop-in">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 id="whiteboard-title" className="text-retro-lg text-indigo-300 font-bold">Whiteboard</h2>
          <button
            onClick={onClose}
            className="retro-btn touch-target rounded bg-slate-700 px-2 py-1 text-xs text-slate-300"
            aria-label="Close whiteboard"
          >
            ESC
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Tool select */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => onToolChange('pen')}
              className={`retro-btn rounded px-2 py-1 text-xs ${
                tool === 'pen'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-700 text-slate-300'
              }`}
              aria-label="Pen tool"
              aria-pressed={tool === 'pen'}
            >
              Pen
            </button>
            <button
              onClick={() => onToolChange('eraser')}
              className={`retro-btn rounded px-2 py-1 text-xs ${
                tool === 'eraser'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-700 text-slate-300'
              }`}
              aria-label="Eraser tool"
              aria-pressed={tool === 'eraser'}
            >
              Eraser
            </button>
          </div>

          {/* Color swatches */}
          <div className="flex items-center gap-1" role="radiogroup" aria-label="Brush color">
            {colors.map((c) => (
              <button
                key={c}
                onClick={() => onColorChange(c)}
                className={`h-5 w-5 rounded-sm border transition-transform ${
                  color === c
                    ? 'ring-2 ring-indigo-400 ring-offset-1 ring-offset-slate-900 scale-110'
                    : 'border-slate-600 hover:scale-105'
                }`}
                style={{ backgroundColor: c }}
                aria-label={`Color ${c}`}
                role="radio"
                aria-checked={color === c}
              />
            ))}
          </div>

          {/* Width selector */}
          <div className="flex items-center gap-1" role="radiogroup" aria-label="Brush width">
            {widths.map((w) => (
              <button
                key={w}
                onClick={() => onWidthChange(w)}
                className={`retro-btn rounded px-2 py-1 text-xs ${
                  width === w
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-700 text-slate-300'
                }`}
                aria-label={`Width ${w}px`}
                role="radio"
                aria-checked={width === w}
              >
                {w}px
              </button>
            ))}
          </div>

          {/* Clear */}
          <button
            onClick={onClear}
            className="retro-btn rounded bg-red-800/80 px-2 py-1 text-xs text-red-200 hover:bg-red-700"
            aria-label="Clear whiteboard"
          >
            Clear
          </button>
        </div>

        {/* Canvas */}
        <canvas
          ref={canvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className="w-full rounded border border-slate-700 bg-slate-950 cursor-crosshair touch-none"
          style={{ imageRendering: 'auto', aspectRatio: `${CANVAS_WIDTH} / ${CANVAS_HEIGHT}` }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          data-testid="whiteboard-canvas"
        />
      </div>
    </div>
  );
};
