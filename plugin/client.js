window.__ModuleLoader__.load({
  id: '@local/dsh-mouse-permission',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const KEY = 'dsh.mousePermission';
    const EVENT = 'dsh:mouse-permission';

    // ── 程序层通道 ───────────────────────────────────────────────────────
    // Host 侧不要再靠 OCR 看这个胶囊是不是绿的（窗口一挪/一滚就判不出来，
    // 还可能读到聊天正文里的「鼠标·已授权」而误判）。这里由插件主动上报。
    //
    // 通道优先级：
    //   ① 图片信标 GET /beacon  —— 不受 CORS 预检限制，最不容易被拦
    //   ② fetch POST /state     —— 若 CSP 允许则同时用
    // 两个都试；都不通也不影响按钮本身（Host 会退回 OCR）。
    const BRIDGE = 'http://127.0.0.1:18765';
    // 本机 token：由桥在自己的 state 目录生成，仓库里替换成 __BRIDGE_TOKEN__
    const BRIDGE_TOKEN = '__BRIDGE_TOKEN__';
    const HEARTBEAT_MS = 5000;
    let lastMode = 'unknown';

    function sendBeacon(granted) {
      try {
        const img = new Image();
        // 不带 no-referrer：桥要靠 Referer 判断来源
        img.src = BRIDGE + '/beacon?k=' + BRIDGE_TOKEN + '&granted=' + (granted ? '1' : '0') + '&t=' + Date.now();
        lastMode = 'beacon';
        return true;
      } catch (err) {
        return false;
      }
    }

    function pushToBridge(granted) {
      sendBeacon(granted);
      try {
        window.fetch(BRIDGE + '/state?k=' + BRIDGE_TOKEN, {
          method: 'POST',
          mode: 'no-cors',
          headers: { 'Content-Type': 'text/plain' },
          body: JSON.stringify({ granted: !!granted, origin: 'mouse-permission-pill' }),
        }).catch(function () { /* 桥没起来就算了 */ });
      } catch (err) {
        /* 没有 fetch 也不影响信标 */
      }
    }

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
        pushToBridge(readGranted());
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
        if (!window.__DSH_MOUSE_BRIDGE_TIMER__) {
          pushToBridge(readGranted());
          window.__DSH_MOUSE_BRIDGE_TIMER__ = window.setInterval(function () {
            pushToBridge(readGranted());
          }, HEARTBEAT_MS);

          // Electron 会节流后台窗口的定时器；回到前台/聚焦时立刻补一次
          const bump = function bump() { pushToBridge(readGranted()); };
          document.addEventListener('visibilitychange', bump);
          window.addEventListener('focus', bump);
        }

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
