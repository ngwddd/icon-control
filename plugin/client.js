window.__ModuleLoader__.load({
  id: '@local/dsh-mouse-permission',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    // 程序层直报：把授权状态 POST 给本地桥（Host 读文件，不再依赖 OCR 看颜色）
    const PERMISSION_BRIDGE = 'http://127.0.0.1:18765/state';
    const BRIDGE_HEARTBEAT_MS = 5000;

    function pushToBridge(granted) {
      try {
        window.fetch(PERMISSION_BRIDGE, {
          method: 'POST',
          mode: 'no-cors',
          headers: { 'Content-Type': 'text/plain' },
          body: JSON.stringify({ granted: !!granted, origin: 'mouse-permission-pill' }),
        }).catch(function () { /* 桥没起来就忽略，Host 会退回 OCR */ });
      } catch (err) {
        /* 环境不支持 fetch 也不影响按钮本身 */
      }
    }

    const KEY = 'dsh.mousePermission';
    const EVENT = 'dsh:mouse-permission';

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
        /* storage disabled: the pill still works for this page load */
      }
    }

    // The label doubles as the machine-readable state: the colour says it at a
    // glance, the text says it unambiguously (granted / denied) for anything
    // that reads the screen instead of the DOM.
    function label(granted) {
      return granted ? '鼠标·已授权' : '鼠标·未授权';
    }

    function MousePermissionPill() {
      const [granted, setGranted] = React.useState(readGranted);

      // 挂载即上报，之后每 5 秒心跳（桥侧 15 秒有效期）
      React.useEffect(function heartbeat() {
        pushToBridge(readGranted());
        const id = window.setInterval(function () {
          pushToBridge(readGranted());
        }, BRIDGE_HEARTBEAT_MS);
        return function () { window.clearInterval(id); };
      }, []);

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

      const toggle = function toggle() {
        const next = !readGranted();
        writeGranted(next);
        setGranted(next);
        window.dispatchEvent(new CustomEvent(EVENT));
        pushToBridge(next);
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
