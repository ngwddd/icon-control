window.__ModuleLoader__.load({
  id: '@local/dsh-mouse-permission',
  factory(require) {
    const React = require('react'), h = React.createElement;
    const EVENT = 'icon-control:confirmed-status';
    const BRIDGE = 'http://127.0.0.1:__BRIDGE_PORT__';
    let confirmed = null, generation = 0, latestRevision = -1, session = null;
    const owner = {};
    if (window.__DSH_MOUSE_BRIDGE_TIMER__) window.clearInterval(window.__DSH_MOUSE_BRIDGE_TIMER__);
    if (window.__DSH_MOUSE_BRIDGE_STREAM__) window.__DSH_MOUSE_BRIDGE_STREAM__.abort();
    window.__DSH_MOUSE_BRIDGE_OWNER__ = owner;
    function publish(value) {
      if (window.__DSH_MOUSE_BRIDGE_OWNER__ !== owner) return;
      confirmed = value;
      try { window.localStorage.removeItem('dsh.mousePermission'); } catch (_) {}
      window.dispatchEvent(new CustomEvent(EVENT));
    }
    async function refresh() {
      const request = ++generation, abort = new AbortController();
      const timeout = window.setTimeout(() => abort.abort(), 2000);
      try {
        const response = await window.fetch(BRIDGE + '/status', {
          method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store',
          referrerPolicy: 'no-referrer', signal: abort.signal,
        });
        if (!response.ok) throw new Error('Status unavailable');
        const state = await response.json();
        if (request !== generation || typeof state.granted !== 'boolean') return;
        if (session === state.session && state.revision < latestRevision) return;
        session = state.session; latestRevision = state.revision;
        publish(state.granted);
      } catch (_) { if (request === generation) publish(null); }
      finally { window.clearTimeout(timeout); }
    }
    window.__DSH_MOUSE_BRIDGE_TIMER__ = window.setInterval(refresh, 4000);
    refresh();
    function Pill() {
      const [state, setState] = React.useState(() => confirmed);
      React.useEffect(() => {
        const update = () => setState(confirmed);
        window.addEventListener(EVENT, update);
        return () => window.removeEventListener(EVENT, update);
      }, []);
      const label = state === null ? '控制中心·状态未知' : state ? '控制中心·单会话已授权' : '控制中心·未授权';
      return h('button', {
        type: 'button', onClick: event => {
          if (event && event.isTrusted) window.open('icon-control://permissions');
        },
        'aria-label': label,
        'data-mouse-permission': state === null ? 'unknown' : state ? 'granted' : 'denied',
        title: '打开原生快捷授权胶囊。首次使用请绑定 Agent 和应用。胶囊只显示后端已确认状态。',
        style: { borderRadius: 999, padding: '3px 10px', cursor: 'pointer',
                 color: state === true ? '#2ea043' : state === null ? '#b87c14' : '#8b949e' },
      }, label);
    }
    return { inject: ['slots'], apply(ctx) {
      ctx.slots.inject('conversation.input.right', () => ctx.slots.register({
        name: 'conversation.input.right', id: 'mouse-permission', order: 10, label: '原生权限中心',
      }, Pill));
    }};
  },
});
