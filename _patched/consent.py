"""Human-only native control center; no credentials are embedded in renderer JS."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from computer_mcp import consent_ipc, capabilities

LABELS = {'screen_read':'读取屏幕、OCR 和窗口信息', 'input':'鼠标、切换窗口',
          'input_observe':'读取物理鼠标及按键状态（可选）',
          'text_entry':'在所选应用中输入文本（可能修改或保存文档）', 'window_close':'关闭所选应用窗口',
          'file_write':'写入 Icon Control 专用目录', 'file_delete':'清理专用目录文件',
          'config_write':'修改助手运行设置', 'process':'启动已批准的应用'}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--broker-session')
    args=parser.parse_args()
    from computer_mcp import permission
    permission._ensure_bridge()
    if not args.broker_session:
        consent_ipc.request('open')
        return
    def ipc(command,**fields):
        return consent_ipc.request(command,ui_nonce=args.broker_session,**fields)
    root = tk.Tk(); root.title('Icon Control — Permissions')
    scale=max(1.0,root.winfo_fpixels('1i')/96.0)
    width=min(int(650*scale),root.winfo_screenwidth()-80)
    height=min(int(720*scale),root.winfo_screenheight()-100)
    left=max(0,(root.winfo_screenwidth()-width)//2)
    top=max(0,(root.winfo_screenheight()-height)//2)
    root.geometry(f'{width}x{height}+{left}+{top}')
    root.minsize(min(width,int(600*scale)),min(height,int(600*scale)))
    frame = ttk.Frame(root, padding=16); frame.pack(fill='both',expand=True)
    status = tk.StringVar(value='正在连接权限服务…')
    ttk.Label(frame, textvariable=status, wraplength=610).pack(fill='x', pady=(0,12))
    ttk.Label(frame,text='选择一个 Agent 会话（授权不会共享给其他客户端）').pack(anchor='w')
    agents = ttk.Combobox(frame, state='readonly'); agents.pack(fill='x', pady=6)
    agent_ids = []
    options = {}
    for scope in sorted(capabilities.SCOPES):
        options[scope] = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame,text=LABELS[scope],variable=options[scope]).pack(anchor='w')
    ttk.Label(frame,text='允许操作的现有应用（PID 及启动时间绑定）：').pack(anchor='w',pady=(12,4))
    applications = tk.Listbox(frame,selectmode='multiple',exportselection=False,height=6)
    applications.pack(fill='both',expand=True)
    records = []
    launches = []
    desired = [False]

    def refresh(initial=False):
        try:
            previous_id=agent_ids[agents.current()] if 0<=agents.current()<len(agent_ids) else None
            previous_apps=[records[i] for i in applications.curselection()]
            result = ipc('status')
            state=result['state']
            prior=state.get('authorization',{}) if initial and state.get('granted') else {}
            if prior and not capabilities.validate(prior):prior={}
            wanted_id=prior.get('agent_session') or previous_id
            wanted_apps=prior.get('applications',[]) if prior else previous_apps
            agent_ids[:] = [a['id'] for a in result['agents']]
            agents['values'] = [a['label']+' · '+a['id'][:10] for a in result['agents']]
            if wanted_id in agent_ids:agents.current(agent_ids.index(wanted_id))
            elif initial and len(agent_ids) == 1:agents.current(0)
            else:agents.set('')
            if prior:
                for scope,var in options.items():var.set(scope in prior.get('scopes',[]))
            import win32gui, win32process, os
            records.clear(); applications.delete(0,'end')
            seen = set()
            def add(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd): return
                title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if not title or pid in seen or pid == os.getpid(): return
                try: record = capabilities.process_record(pid)
                except Exception: return
                seen.add(pid); records.append(record)
                applications.insert('end', f'{pid} · {title[:70]}')
                if record in wanted_apps:applications.selection_set(len(records)-1)
            win32gui.EnumWindows(add,None)
            status.set('后端已确认：'+('已授权（仅所选会话及能力）' if state.get('granted') else '未授权'))
            if prior:status.set('已预填后端原有授权范围；请点击“授权所选范围”确认本窗口续期。')
        except Exception:
            desired[0] = False
            status.set('状态未知：连接失败。助手不接受新授权，请检查权限服务。')

    def grant():
        desired[0] = False
        try:
            index = agents.current()
            if index < 0: raise ValueError('请先启动 MCP 客户端并刷新会话列表')
            selected = [scope for scope,var in options.items() if var.get()]
            if not selected: raise ValueError('请至少选择一种能力')
            if set(selected)&{'input','text_entry','window_close'} and not applications.curselection():
                raise ValueError('请在应用列表选中允许操作的应用（蓝色高亮）')
            result = ipc('grant', agent_session=agent_ids[index], scopes=selected,
                                        applications=[records[i] for i in applications.curselection()], launches=launches)
            if result.get('granted') is not True:raise RuntimeError('后端尚未确认授权')
            desired[0] = True
            confirmed_agent[0] = agent_ids[index]
            status.set('后端已确认：已授权。30 分钟后到期；关闭本窗口将撤销。')
        except Exception as exc:
            status.set('状态未知或未授权：'+str(exc))

    def revoke():
        desired[0] = False
        status.set('正在等待后端确认撤销…')
        try:
            result = ipc('revoke')
            if result.get('granted'): raise RuntimeError('后端尚未撤销')
            status.set('后端已确认：未授权')
        except Exception:
            status.set('状态未知：撤销确认失败；正在发送否定心跳。')

    confirmed_agent = [None]

    def heartbeat():
        try:
            result = ipc('heartbeat', granted=desired[0])
            auth = result.get('authorization', {})
            if result.get('granted') and desired[0] and auth.get('agent_session') == confirmed_agent[0]:
                import time
                left = max(0, int(result.get('authorized_at', 0) + 1800 - time.time()))
                apps = ', '.join(str(app['pid']) for app in auth.get('applications', []))
                status.set(f"后端已确认 · {confirmed_agent[0][:10]} · PID {apps} · 剩余 {left//60}:{left%60:02d}")
                lamp.configure(fg='green')
            else:
                desired[0] = False
                status.set('后端已确认：未授权')
                lamp.configure(fg='gray')
        except Exception:
            desired[0] = False
            status.set('状态未知：通信失败，已停止续期。')
            lamp.configure(fg='darkorange')
        root.after(4000, heartbeat)

    buttons = ttk.Frame(frame); buttons.pack(before=applications,side='bottom',fill='x',pady=(12,0))
    ttk.Button(buttons,text='刷新会话与应用',command=refresh).pack(side='left')
    ttk.Button(buttons,text='授权所选范围',command=grant).pack(side='left',padx=12)
    ttk.Button(buttons,text='立即撤销',command=revoke).pack(side='left')
    def approve_launch():
        path = filedialog.askopenfilename(parent=root,title='批准可启动的程序',filetypes=[('Windows 程序','*.exe')])
        if not path: return
        arguments = simpledialog.askstring('固定启动参数','允许的完整启动参数（可留空）：',parent=root)
        if arguments is None: return
        try:
            launches.append(capabilities.launch_record(path,arguments))
            status.set('已选择待批准的启动程序；请点击“授权所选范围”提交。')
        except Exception as exc: messagebox.showerror('无法批准',str(exc),parent=root)
    ttk.Button(frame,text='选择允许启动的程序及固定参数…',command=approve_launch).pack(
        before=applications,side='bottom',anchor='w',pady=(8,0))
    capsule = tk.Toplevel(root)
    capsule.title('Icon Control — Permissions · 快捷授权')
    capsule.attributes('-topmost', True)
    capsule.resizable(False, False)
    caption = tk.StringVar(value='正在核对常用目标…')
    ttk.Label(capsule, textvariable=caption, wraplength=360).pack(padx=12, pady=6)
    lamp = tk.Label(capsule, textvariable=status, wraplength=360)
    lamp.pack(fill='x')

    def show_settings():
        root.deiconify()
        root.lift()
        refresh()

    def preview():
        plan = ipc('quick_preview')
        if plan.get('status') == 'ready':
            app = plan['applications'][0]
            caption.set(f"{plan['label']} · {plan['agent_session'][:10]}\n{app['exe']} · PID {app['pid']}\n屏幕读取、鼠标与文字输入 · 最长 30 分钟")
        else:
            caption.set('请先在设置中绑定一个 Agent 和目标应用')
        return plan

    def bind_target():
        try:
            selected = applications.curselection()
            if agents.current() < 0 or len(selected) != 1:
                raise ValueError('请选择一个 Agent 和一个应用')
            ipc('quick_bind', agent_session=agent_ids[agents.current()], app=records[selected[0]])
            if preview().get('status') == 'ready':
                root.withdraw()
        except Exception as exc:
            messagebox.showerror('绑定失败', str(exc), parent=root)

    def quick():
        try:
            result = ipc('quick_grant')
            state = result.get('state', {})
            if result.get('status') == 'granted' and state.get('granted') is True:
                desired[0] = True
                confirmed_agent[0] = state['authorization']['agent_session']
                status.set('后端已确认：常用操作已授权')
                lamp.configure(fg='green')
            else:
                desired[0] = False
                status.set('目标需要重新确认')
                lamp.configure(fg='darkorange')
                show_settings()
        except Exception:
            desired[0] = False
            status.set('状态未知：连接失败')
            lamp.configure(fg='darkorange')

    ttk.Button(capsule,text='一键授权常用操作',command=quick).pack(fill='x')
    ttk.Button(capsule,text='一键撤销',command=revoke).pack(fill='x')
    ttk.Button(capsule,text='绑定目标与高级设置',command=show_settings).pack(fill='x')
    ttk.Button(buttons,text='保存常用目标',command=bind_target).pack(side='left')
    def close(): revoke(); root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    capsule.protocol('WM_DELETE_WINDOW',close)
    refresh(True)
    root.withdraw()
    try: preview()
    except Exception: status.set('状态未知：连接失败')
    root.after(4000,heartbeat)
    root.mainloop()

if __name__ == '__main__': main()
