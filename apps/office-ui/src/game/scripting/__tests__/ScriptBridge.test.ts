import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock PhaserGame module
const mockEmit = vi.fn();
vi.mock('../../PhaserGame', () => ({
  gameEventBus: {
    emit: mockEmit,
    on: vi.fn(() => vi.fn()),
  },
}));

// Mock ScriptAPI
vi.mock('../ScriptAPI', () => ({
  buildScriptAPISource: () => '/* mock API */',
}));

describe('ScriptBridge', () => {
  let ScriptBridge: typeof import('../ScriptBridge').ScriptBridge;

  beforeEach(async () => {
    mockEmit.mockClear();
    // Reset module cache to get fresh imports
    const mod = await import('../ScriptBridge');
    ScriptBridge = mod.ScriptBridge;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates an instance without errors', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);
    expect(bridge).toBeDefined();
    bridge.destroy();
  });

  it('loadScript creates a hidden iframe', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('https://example.com/script.js');

    expect(appendSpy).toHaveBeenCalled();
    const iframe = appendSpy.mock.calls[0][0] as HTMLIFrameElement;
    expect(iframe.tagName).toBe('IFRAME');
    expect(iframe.style.display).toBe('none');
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts');

    bridge.destroy();
    appendSpy.mockRestore();
  });

  it('loadScript sanitizes URLs - allows https', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('https://example.com/safe.js');

    const iframe = appendSpy.mock.calls[0][0] as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain('https://example.com/safe.js');

    bridge.destroy();
    appendSpy.mockRestore();
  });

  it('loadScript sanitizes URLs - blocks javascript:', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('javascript:alert(1)');

    const iframe = appendSpy.mock.calls[0][0] as HTMLIFrameElement;
    // Sanitized URL should be empty
    expect(iframe.srcdoc).not.toContain('javascript:');

    bridge.destroy();
    appendSpy.mockRestore();
  });

  it('notifyAreaEvent sends postMessage to iframes', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('https://example.com/script.js');

    const iframe = appendSpy.mock.calls[0][0] as HTMLIFrameElement;
    const mockPostMessage = vi.fn();
    Object.defineProperty(iframe, 'contentWindow', {
      value: { postMessage: mockPostMessage },
    });

    bridge.notifyAreaEvent('TestZone', 'enter');

    expect(mockPostMessage).toHaveBeenCalledWith(
      { __selva_event: true, type: 'area.onEnter', areaName: 'TestZone' },
      '*',
    );

    bridge.destroy();
    appendSpy.mockRestore();
  });

  it('notifyAreaEvent with leave sends correct type', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('https://example.com/script.js');

    const iframe = appendSpy.mock.calls[0][0] as HTMLIFrameElement;
    const mockPostMessage = vi.fn();
    Object.defineProperty(iframe, 'contentWindow', {
      value: { postMessage: mockPostMessage },
    });

    bridge.notifyAreaEvent('MeetingRoom', 'leave');

    expect(mockPostMessage).toHaveBeenCalledWith(
      { __selva_event: true, type: 'area.onLeave', areaName: 'MeetingRoom' },
      '*',
    );

    bridge.destroy();
    appendSpy.mockRestore();
  });

  it('destroy removes all iframes and event listeners', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    const appendSpy = vi.spyOn(document.body, 'appendChild');
    bridge.loadScript('https://example.com/a.js');
    bridge.loadScript('https://example.com/b.js');

    const iframes = appendSpy.mock.calls.map((c) => c[0] as HTMLIFrameElement);
    const removeSpy1 = vi.spyOn(iframes[0], 'remove');
    const removeSpy2 = vi.spyOn(iframes[1], 'remove');

    bridge.destroy();

    expect(removeSpy1).toHaveBeenCalled();
    expect(removeSpy2).toHaveBeenCalled();

    appendSpy.mockRestore();
  });

  it('handles postMessage with chat.sendMessage command', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    // Simulate a postMessage from an iframe
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { __selva: true, type: 'chat.sendMessage', content: 'Hello' },
      }),
    );

    expect(mockEmit).toHaveBeenCalledWith('script-chat', 'Hello');

    bridge.destroy();
  });

  it('handles postMessage with ui.openPopup command', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    window.dispatchEvent(
      new MessageEvent('message', {
        data: {
          __selva: true,
          type: 'ui.openPopup',
          title: 'Notice',
          content: 'Welcome!',
        },
      }),
    );

    expect(mockEmit).toHaveBeenCalledWith('show_popup', {
      title: 'Notice',
      content: 'Welcome!',
    });

    bridge.destroy();
  });

  it('handles postMessage with camera.moveTo command', () => {
    const panFn = vi.fn();
    const mockScene = { cameras: { main: { pan: panFn } } } as any;
    const bridge = new ScriptBridge(mockScene);

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { __selva: true, type: 'camera.moveTo', x: 100, y: 200 },
      }),
    );

    expect(panFn).toHaveBeenCalledWith(100, 200, 500, 'Sine.easeInOut');

    bridge.destroy();
  });

  it('ignores messages without __selva marker', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { type: 'chat.sendMessage', content: 'Sneaky' },
      }),
    );

    expect(mockEmit).not.toHaveBeenCalled();

    bridge.destroy();
  });

  it('ignores commands not in the whitelist', () => {
    const mockScene = { cameras: { main: { pan: vi.fn() } } } as any;
    const bridge = new ScriptBridge(mockScene);

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { __selva: true, type: 'dangerous.eval', code: 'alert(1)' },
      }),
    );

    expect(mockEmit).not.toHaveBeenCalled();

    bridge.destroy();
  });
});
