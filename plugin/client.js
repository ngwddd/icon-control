window.__ModuleLoader__.load({
  id: '@local/dsh-mouse-permission',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const KEY = 'dsh.mousePermission';
    const EVENT = 'dsh:mouse-permission';

    // Authenticated CORS requests only; credentials never enter a URL.
    const BRIDGE = 'http://127.0.0.1:__BRIDGE_PORT__';
    const BRIDGE_TOKEN = '__BRIDGE_TOKEN__';
    const HEARTBEAT_MS = 5000;
    const CLIENT = (window.crypto && window.crypto.randomUUID)
      ? window.crypto.randomUUID() : String(Date.now()) + Math.random().toString(36);
    let lastMode = 'unknown';
    let actionSequence = 0;

    function headers() {
      return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + BRIDGE_TOKEN };
    }

    function syncFromBridge(sequence) {
      return window.fetch(BRIDGE + '/state', {
        method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store',
        referrerPolicy: 'no-referrer', headers: headers(),
      }).then(function (response) {
        if (!response.ok) throw new Error('Bridge state unavailable');
        return response.json();
      }).then(function (state) {
        if (sequence !== actionSequence || typeof state.granted !== 'boolean') return;
        if (readGranted() !== state.granted) {
          writeGranted(state.granted);
          window.dispatchEvent(new CustomEvent(EVENT));
        }
      });
    }

    function pushToBridge(granted, event = 'hb') {
      if (!BRIDGE_TOKEN || BRIDGE_TOKEN.startsWith('__')) return;
      const sequence = event === 'action' ? ++actionSequence : 0;
      const currentSequence = actionSequence;
      const actionAt = event === 'action' ? Date.now() : 0;
      window.fetch(BRIDGE + '/state', {
        method: 'POST', mode: 'cors', credentials: 'omit', cache: 'no-store',
        referrerPolicy: 'no-referrer', headers: headers(),
        body: JSON.stringify({ granted: !!granted, origin: 'mouse-permission-pill',
                              client: CLIENT, event, sequence, action_at: actionAt }),
      }).then(function (response) {
        if (!response.ok) throw new Error('Bridge request rejected');
        lastMode = 'authenticated';
        return syncFromBridge(currentSequence);
      }).catch(function () { lastMode = 'unavailable'; });
    }

    function ensureHeartbeat() {
      if (window.__DSH_MOUSE_BRIDGE_OWNER__ === CLIENT) return;
      if (window.__DSH_MOUSE_BRIDGE_TIMER__) window.clearInterval(window.__DSH_MOUSE_BRIDGE_TIMER__);
      if (window.__DSH_MOUSE_BRIDGE_STREAM__) window.__DSH_MOUSE_BRIDGE_STREAM__.abort();
      if (window.__DSH_MOUSE_BRIDGE_BUMP__) {
        document.removeEventListener('visibilitychange', window.__DSH_MOUSE_BRIDGE_BUMP__);
        window.removeEventListener('focus', window.__DSH_MOUSE_BRIDGE_BUMP__);
      }
      window.__DSH_MOUSE_BRIDGE_OWNER__ = CLIENT;
      const bump = function () { pushToBridge(readGranted()); };
      window.__DSH_MOUSE_BRIDGE_BUMP__ = bump;
      window.__DSH_MOUSE_BRIDGE_TIMER__ = window.setInterval(bump, HEARTBEAT_MS);
      document.addEventListener('visibilitychange', bump);
      window.addEventListener('focus', bump);
      bump();
      // Background Chromium windows throttle timers to a minute. Network
      // arrivals remain event driven; an unresponsive renderer still expires.
      const stream = new AbortController();
      window.__DSH_MOUSE_BRIDGE_STREAM__ = stream;
      window.fetch(BRIDGE + '/events', {
        method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store',
        referrerPolicy: 'no-referrer', headers: headers(), signal: stream.signal,
      }).then(async function (response) {
        if (!response.ok || !response.body) throw new Error('Bridge events unavailable');
        const reader = response.body.getReader();
        try {
          while (!stream.signal.aborted) {
            const chunk = await reader.read();
            if (stream.signal.aborted || chunk.done) break;
            if (chunk.value && chunk.value.length) bump();
          }
        } finally { await reader.cancel(); }
      }).catch(function () { /* fallback never grants or extends authority itself */ });
    }

    // Some hosts reload the factory without rerunning apply().
    ensureHeartbeat();

    // ── 状态读写 ─────────────────────────────────────────────────────────
    function readGranted() {
      try {
        return window.localStorage.getItem(KEY) === '1';
      } catch (err) {
        return false;
      }
    }

    function writeGranted(value) {
      try {
        window.localStorage.setItem(KEY, value ? '1' : '0');
      } catch (err) {
        /* 存储被禁用时，本页仍可用 */
      }
    }

    // 文案既是给人看的，也是机器可读的（除颜色外还有明确文字）
    function label(granted) {
      return granted ? '鼠标·已授权' : '鼠标·未授权';
    }

    function MousePermissionPill() {
      const [granted, setGranted] = React.useState(readGranted);

      React.useEffect(function subscribe() {
        const sync = function sync() {
          setGranted(readGranted());
        };
        window.addEventListener('storage', sync);
        window.addEventListener(EVENT, sync);
        return function cleanup() {
          window.removeEventListener('storage', sync);
          window.removeEventListener(EVENT, sync);
        };
      }, []);

      React.useEffect(function reportOnMount() {
        ensureHeartbeat();
        pushToBridge(readGranted());
      }, []);

      const toggle = function toggle(event) {
        if (!event || !event.isTrusted) return;
        const next = !readGranted();
        writeGranted(next);
        setGranted(next);
        window.dispatchEvent(new CustomEvent(EVENT));
        pushToBridge(next, 'action');
      };

      const dot = {
        width: 8,
        height: 8,
        borderRadius: '50%',
        flex: '0 0 auto',
        background: granted ? '#2ea043' : '#8b949e',
        boxShadow: granted ? '0 0 0 3px rgba(46, 160, 67, 0.18)' : 'none',
        transition: 'background 120ms ease, box-shadow 120ms ease',
      };

      return h(
        'button',
        {
          type: 'button',
          onClick: toggle,
          'data-mouse-permission': granted ? 'granted' : 'denied',
          'data-mouse-bridge': lastMode,
          'aria-label': label(granted),
          'aria-pressed': granted,
          title: granted
            ? '鼠标接管：已授权 —— 代理可以操纵鼠标。点一下收回权限。'
            : '鼠标接管：未授权 —— 代理不得操纵鼠标。点一下授权。',
          style: {
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            height: 26,
            padding: '0 10px',
            borderRadius: 999,
            cursor: 'pointer',
            font: 'inherit',
            fontSize: 12,
            lineHeight: 1,
            whiteSpace: 'nowrap',
            color: granted ? '#2ea043' : 'var(--dsh-color-text-secondary, #8b949e)',
            background: granted ? 'rgba(46, 160, 67, 0.12)' : 'transparent',
            border:
              '1px solid ' + (granted ? 'rgba(46, 160, 67, 0.45)' : 'rgba(139, 148, 158, 0.35)'),
            transition: 'background 120ms ease, border-color 120ms ease, color 120ms ease',
          },
        },
        h('span', { style: dot, 'aria-hidden': true }),
        label(granted),
      );
    }

    return {
      inject: ['slots'],
      apply: function apply(ctx) {
        // 心跳放在插件级别（不是组件 effect）：组件热重载/重挂时 effect 的清理
        // 会把定时器清掉，心跳就断了 —— 实测过一次：胶囊还在，Host 收不到上报，
        // 只能退回 OCR。放在这里，重挂也不会断。
        ensureHeartbeat();

        ctx.slots.inject('conversation.input.right', function register() {
          return ctx.slots.register(
            {
              name: 'conversation.input.right',
              id: 'mouse-permission',
              order: 10,
              label: '鼠标接管权限',
            },
            MousePermissionPill,
          );
        });
      },
    };
  },
});
