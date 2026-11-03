// DSH 胶囊已按用户要求移除：授权入口改为原生窗口 + 托盘 + 全局热键（Ctrl+Alt+Shift+F9）。
// 保留这个空模块只是为了已注册的插件入口不会因为缺文件而报错。
window.__ModuleLoader__.load({
  id: '@local/dsh-mouse-permission',
  factory() {
    return { inject: [], apply() {} };
  },
});
