import { describe, it, expect } from 'vitest';
import { buildScriptAPISource } from '../ScriptAPI';

describe('ScriptAPI', () => {
  it('builds a non-empty source string', () => {
    const source = buildScriptAPISource();
    expect(source).toBeTruthy();
    expect(typeof source).toBe('string');
  });

  it('contains the AS namespace definition', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('window.AS');
  });

  it('exposes AS.chat.sendMessage', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('chat:');
    expect(source).toContain('sendMessage');
  });

  it('exposes AS.camera.moveTo', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('camera:');
    expect(source).toContain('moveTo');
  });

  it('exposes AS.player.moveTo', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('player:');
  });

  it('exposes AS.ui.openPopup and AS.ui.openCoWebsite', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('openPopup');
    expect(source).toContain('openCoWebsite');
  });

  it('exposes AS.onPlayerEntersArea and AS.onPlayerLeavesArea', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('onPlayerEntersArea');
    expect(source).toContain('onPlayerLeavesArea');
  });

  it('sends __selva marker via postMessage', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('__selva: true');
  });

  it('listens for __selva_event messages', () => {
    const source = buildScriptAPISource();
    expect(source).toContain('__selva_event');
  });

  it('handles area.onEnter and area.onLeave events', () => {
    const source = buildScriptAPISource();
    expect(source).toContain("'area.onEnter'");
    expect(source).toContain("'area.onLeave'");
  });
});
