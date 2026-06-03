/**
 * Defines the AS.* namespace commands available to map scripts.
 * Each command is serialized to a postMessage payload and handled by ScriptBridge.
 */

export type ScriptCommand =
  | { type: 'chat.sendMessage'; content: string }
  | { type: 'camera.moveTo'; x: number; y: number }
  | { type: 'player.moveTo'; x: number; y: number }
  | { type: 'ui.openPopup'; title: string; content: string }
  | { type: 'ui.openCoWebsite'; url: string; title?: string }
  | { type: 'area.onEnter'; areaName: string }
  | { type: 'area.onLeave'; areaName: string };

export type AreaCallback = () => void;

/**
 * Build the AS namespace code that gets injected into the script iframe.
 * This is a string that will be eval'd inside the iframe context.
 * All commands are sent via postMessage to the parent window.
 */
export function buildScriptAPISource(): string {
  return `
(function() {
  var _areaCallbacks = { enter: {}, leave: {} };

  window.AS = {
    chat: {
      sendMessage: function(content) {
        parent.postMessage({ __selva: true, type: 'chat.sendMessage', content: content }, '*');
      }
    },
    camera: {
      moveTo: function(x, y) {
        parent.postMessage({ __selva: true, type: 'camera.moveTo', x: x, y: y }, '*');
      }
    },
    player: {
      moveTo: function(x, y) {
        parent.postMessage({ __selva: true, type: 'player.moveTo', x: x, y: y }, '*');
      }
    },
    ui: {
      openPopup: function(title, content) {
        parent.postMessage({ __selva: true, type: 'ui.openPopup', title: title, content: content }, '*');
      },
      openCoWebsite: function(url, title) {
        parent.postMessage({ __selva: true, type: 'ui.openCoWebsite', url: url, title: title }, '*');
      }
    },
    onPlayerEntersArea: function(areaName, callback) {
      _areaCallbacks.enter[areaName] = _areaCallbacks.enter[areaName] || [];
      _areaCallbacks.enter[areaName].push(callback);
    },
    onPlayerLeavesArea: function(areaName, callback) {
      _areaCallbacks.leave[areaName] = _areaCallbacks.leave[areaName] || [];
      _areaCallbacks.leave[areaName].push(callback);
    }
  };

  window.addEventListener('message', function(event) {
    var data = event.data;
    if (!data || !data.__selva_event) return;
    var callbacks;
    if (data.type === 'area.onEnter') {
      callbacks = _areaCallbacks.enter[data.areaName] || [];
    } else if (data.type === 'area.onLeave') {
      callbacks = _areaCallbacks.leave[data.areaName] || [];
    }
    if (callbacks) {
      for (var i = 0; i < callbacks.length; i++) {
        try {
          callbacks[i]();
        } catch (e) {
          // Forward script-author errors to the parent so the host's
          // dev-only logger can surface them; raw console.* would leak
          // into production browser consoles for end users.
          parent.postMessage(
            { __selva: true, type: 'script.error', message: String(e) },
            '*'
          );
        }
      }
    }
  });
})();
`;
}
