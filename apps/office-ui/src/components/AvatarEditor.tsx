'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import type { AvatarConfig } from '@autoswarm/shared-types';
import {
  SKIN_TONES,
  HAIR_COLORS,
  OUTFIT_COLORS,
  HAIR_STYLE_NAMES,
  ACCESSORY_NAMES,
  resolveColorMap,
} from '@autoswarm/shared-types';
import { composeLayers } from '@/game/sprite-data/renderer';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import bodyTemplates from '@autoswarm/shared-types/src/sprite-data/body.json';
import hairTemplates from '@autoswarm/shared-types/src/sprite-data/hair.json';
import accessoryTemplates from '@autoswarm/shared-types/src/sprite-data/accessories.json';

const HAIR_STYLE_KEYS = ['short', 'long', 'spiky', 'curly'] as const;
const PLAYER_ACC_KEYS = ['glasses', 'crown', 'headphones', 'hat'] as const;

interface AvatarEditorProps {
  open: boolean;
  initialConfig: AvatarConfig;
  onSave: (config: AvatarConfig) => void;
  onClose: () => void;
}

/** Draw the avatar onto a 2D canvas context at 32x32 resolution using shared templates */
function drawAvatar(ctx: CanvasRenderingContext2D, config: AvatarConfig) {
  ctx.clearRect(0, 0, 32, 32);

  const colorMap = resolveColorMap(config);

  const layers: ((string | null)[][] | null)[] = [
    bodyTemplates.front_stand,
  ];

  // Hair overlay
  if (config.hairStyle >= 0 && config.hairStyle < HAIR_STYLE_KEYS.length) {
    const styleKey = HAIR_STYLE_KEYS[config.hairStyle];
    const hairStyle = hairTemplates[styleKey];
    if (hairStyle?.front) {
      layers.push(hairStyle.front);
    }
  }

  // Accessory overlay
  if (config.accessory >= 0 && config.accessory < PLAYER_ACC_KEYS.length) {
    const accKey = PLAYER_ACC_KEYS[config.accessory];
    const accGrid = accessoryTemplates.player?.[accKey];
    if (accGrid) {
      layers.push(accGrid);
    }
  }

  composeLayers(ctx, 0, 0, layers, colorMap);
}

function AvatarPreview({ config }: { config: AvatarConfig }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;
    drawAvatar(ctx, config);
  }, [config]);

  return (
    <canvas
      ref={canvasRef}
      width={32}
      height={32}
      className="block"
      style={{
        width: 128,
        height: 128,
        imageRendering: 'pixelated',
      }}
    />
  );
}

function ColorSwatch({
  color,
  selected,
  onClick,
  label,
}: {
  color: string;
  selected: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`h-8 w-8 rounded border-2 transition-transform active:scale-90 ${
        selected ? 'ring-2 ring-indigo-400 ring-offset-2 ring-offset-slate-900 border-white scale-110' : 'border-slate-600 hover:border-slate-400'
      }`}
      style={{ backgroundColor: color }}
    />
  );
}

function OptionButton({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-3 py-1 text-xs transition-all retro-btn active:scale-90 ${
        selected
          ? 'bg-indigo-600 text-white'
          : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
      }`}
    >
      {label}
    </button>
  );
}

export function AvatarEditor({ open, initialConfig, onSave, onClose }: AvatarEditorProps) {
  const [config, setConfig] = useState<AvatarConfig>(initialConfig);
  const trapRef = useFocusTrap<HTMLDivElement>(open);

  const update = useCallback((partial: Partial<AvatarConfig>) => {
    setConfig((prev) => ({ ...prev, ...partial }));
  }, []);

  const handleSave = useCallback(() => {
    onSave(config);
  }, [config, onSave]);

  // Escape to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-modal flex items-center justify-center bg-black/70 animate-fade-in" role="dialog" aria-modal="true" aria-label="Avatar editor">
      <div ref={trapRef} className="w-96 retro-panel pixel-border-accent p-6 animate-pop-in">
        <h2 className="mb-4 text-center pixel-text text-retro-lg text-slate-200">
          CUSTOMIZE YOUR AVATAR
        </h2>

        {/* Live Canvas Preview */}
        <div className="mb-4 flex justify-center">
          <div className="rounded-lg border border-slate-700 bg-slate-950 p-2">
            <AvatarPreview config={config} />
          </div>
        </div>

        {/* Skin Tone */}
        <div className="mb-3">
          <label className="mb-1 block pixel-text text-retro-xs text-slate-400">Skin Tone</label>
          <div className="flex gap-2">
            {SKIN_TONES.map((color, i) => (
              <ColorSwatch
                key={color}
                color={color}
                selected={config.skinTone === i}
                onClick={() => update({ skinTone: i })}
                label={`Skin tone ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Hair Style */}
        <div className="mb-3">
          <label className="mb-1 block pixel-text text-retro-xs text-slate-400">Hair Style</label>
          <div className="flex flex-wrap gap-1">
            <OptionButton
              label="Bald"
              selected={config.hairStyle === -1}
              onClick={() => update({ hairStyle: -1 })}
            />
            {HAIR_STYLE_NAMES.map((name, i) => (
              <OptionButton
                key={name}
                label={name}
                selected={config.hairStyle === i}
                onClick={() => update({ hairStyle: i })}
              />
            ))}
          </div>
        </div>

        {/* Hair Color */}
        {config.hairStyle >= 0 && (
          <div className="mb-3">
            <label className="mb-1 block pixel-text text-retro-xs text-slate-400">Hair Color</label>
            <div className="flex gap-2">
              {HAIR_COLORS.map((color, i) => (
                <ColorSwatch
                  key={color}
                  color={color}
                  selected={config.hairColor === i}
                  onClick={() => update({ hairColor: i })}
                  label={`Hair color ${i + 1}`}
                />
              ))}
            </div>
          </div>
        )}

        {/* Outfit Color */}
        <div className="mb-3">
          <label className="mb-1 block pixel-text text-retro-xs text-slate-400">Outfit Color</label>
          <div className="flex gap-2">
            {OUTFIT_COLORS.map((color, i) => (
              <ColorSwatch
                key={color}
                color={color}
                selected={config.outfitColor === i}
                onClick={() => update({ outfitColor: i })}
                label={`Outfit color ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Accessory */}
        <div className="mb-4">
          <label className="mb-1 block pixel-text text-retro-xs text-slate-400">Accessory</label>
          <div className="flex flex-wrap gap-1">
            {ACCESSORY_NAMES.map((name, i) => (
              <OptionButton
                key={name}
                label={name}
                selected={config.accessory === i - 1}
                onClick={() => update({ accessory: i - 1 })}
              />
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded bg-slate-700 px-4 py-2 text-xs text-slate-300 retro-btn hover:bg-slate-600"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white retro-btn hover:bg-indigo-500"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
