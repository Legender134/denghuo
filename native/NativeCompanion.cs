// Local WPF presentation host. No game writes or calculations occur here.
// C# 4, explicitly pinned .NET Framework 4.0 reference assemblies.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Runtime.Versioning;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Threading;
using Forms = System.Windows.Forms;
[assembly: TargetFramework(".NETFramework,Version=v4.0")]
namespace Denghuo.Native {
    static class Data {
        public static string Text(IDictionary<string, object> d, string k, string fallback) { object v; return d.TryGetValue(k, out v) && v != null ? Convert.ToString(v) : fallback; }
        public static bool Flag(IDictionary<string, object> d, string k) { object v; return d.TryGetValue(k, out v) && v is bool && (bool)v; }
        public static long Number(IDictionary<string, object> d, string k) { object v; return d.TryGetValue(k, out v) ? Convert.ToInt64(v) : 0; }
        public static Dictionary<string, object> Object(IDictionary<string, object> d, string k) { object v; return d.TryGetValue(k, out v) && v is Dictionary<string, object> ? (Dictionary<string, object>)v : new Dictionary<string, object>(); }
        public static object[] Array(IDictionary<string, object> d, string k) { object v; if (!d.TryGetValue(k, out v) || v == null) return new object[0]; if (v is object[]) return (object[])v; var a = v as ArrayList; return a == null ? new object[0] : a.ToArray(); }
        public static Dictionary<string, object> Map(params object[] pairs) { var d = new Dictionary<string, object>(); for (int i = 0; i < pairs.Length; i += 2) d[(string)pairs[i]] = pairs[i + 1]; return d; }
    }

    sealed class Choice {
        public string Id, Text, Component;
        public Choice(string id, string text, string component = null) { Id = id; Text = text; Component = component; }
        public override string ToString() { return Text; }
    }

    // Request identity outlives a modal dialog and its delayed return.
    sealed class ExitRequests {
        readonly HashSet<string> retired = new HashSet<string>();
        string current;
        public bool IsCurrent(string id) { return !String.IsNullOrEmpty(id) && current == id; }
        public bool Begin(string id) {
            if (String.IsNullOrEmpty(id) || retired.Contains(id) || IsCurrent(id)) return false;
            if (current != null) retired.Add(current);
            current = id; return true;
        }
        public bool Cancel(string id) {
            if (String.IsNullOrEmpty(id)) return false;
            retired.Add(id);
            if (!IsCurrent(id)) return false;
            current = null; return true;
        }
    }


    sealed class Helper {
        const int MaxLine = 524288;
        readonly string session;
        readonly BlockingCollection<string> incoming = new BlockingCollection<string>(128);
        readonly BlockingCollection<string> outgoing = new BlockingCollection<string>(128);
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength=MaxLine, RecursionLimit=64 };
        readonly DispatcherTimer timer = new DispatcherTimer();
        readonly ExitRequests exitRequests = new ExitRequests();
        long request, revision;
        bool stopping;
        public bool Frozen;
        public ManagerForm Manager;
        public LookupForm Lookup;
        public SettingsForm Settings;
        public PlansForm Plans;
        Dialog activeExit;
        NameDialog activeName;
        string activeNamePage;
        public object SaveDraft { get { return activeName!=null && activeNamePage==null && activeName.Dirty ? (object)activeName.Raw() : null; } }
        public void CaptureSaveDraft(Dictionary<string,object> raw) { if(activeName!=null) raw["pending_save"]=SaveDraft; }
        public Helper(string key) {
            session=key;
            Manager=new ManagerForm(this); Lookup=new LookupForm(this); Settings=new SettingsForm(this); Plans=new PlansForm(this);
            Manager.Mount("lookup",Lookup); Manager.Mount("settings",Settings); Manager.Mount("plans",Plans);
            Send("ready","pid",Process.GetCurrentProcess().Id,"system_dpi",Manager.SystemDpi,"framework",Environment.Version.ToString());
            new Thread(Read) { IsBackground=true, Name="native-json-reader" }.Start();
            new Thread(Write) { IsBackground=true, Name="native-json-writer" }.Start();
            // Finish the timer tick before opening a modal dialog. WPF suppresses
            // reentrant ticks, while a modal dispatcher still accepts queued work.
            timer.Interval=TimeSpan.FromMilliseconds(30); timer.Tick+=delegate { Application.Current.Dispatcher.BeginInvoke(DispatcherPriority.Background,new Action(Drain)); }; timer.Start();
        }
        public void Send(string action,params object[] pairs) {
            if(stopping) return;
            var value=Data.Map(pairs); value["version"]=1; value["session"]=session; value["request"]=++request; value["revision"]=revision; value["action"]=action;
            string line=json.Serialize(value); if(line.Length>MaxLine || !outgoing.TryAdd(line)) Fail("窗口暂时繁忙，草稿仍保留；请稍后重试。");
        }
        void Read() { try { using(var reader=new StreamReader(Console.OpenStandardInput(),new UTF8Encoding(false,true),false,4096)) {
            var line=new StringBuilder(); int ch; while((ch=reader.Read())>=0 && !stopping) { if(ch=='\n') { if(!incoming.TryAdd(line.ToString(),500)) throw new IOException("原生输入队列已满"); line.Length=0; } else if(ch!='\r') { line.Append((char)ch); if(line.Length>MaxLine) throw new IOException("协议行超出限制"); } }
        }} catch(Exception e) { Console.Error.WriteLine(e.Message); } incoming.TryAdd("{\"action\":\"eof\"}",500); }
        void Write() { try { using(var writer=new StreamWriter(Console.OpenStandardOutput(),new UTF8Encoding(false),4096)) { writer.AutoFlush=true; foreach(string line in outgoing.GetConsumingEnumerable()) writer.WriteLine(line); } } catch(Exception e) { Console.Error.WriteLine(e.Message); } }
        void Drain() { if(stopping) return; string line; for(int i=0;i<48 && incoming.TryTake(out line);i++) { try {
            var d=json.Deserialize<Dictionary<string,object>>(line); string action=Data.Text(d,"action",""); if(action=="eof") { Shutdown(); return; }
            if(Data.Number(d,"version")!=1 || Data.Text(d,"session","")!=session) throw new IOException("原生协议身份不匹配"); revision=Math.Max(revision,Data.Number(d,"revision"));
            switch(action) {
                case "show": ShowSurface(Data.Text(d,"surface","manager")); break;
                case "hide": HideSurface(Data.Text(d,"surface","manager")); break;
                case "minimize_manager": Manager.WindowState=WindowState.Minimized; break;
                case "manager_state": Manager.Render(d); break;
                case "window_layout": Manager.LayoutRestored=Data.Flag(d,"restored"); Manager.ApplyLayout(Data.Object(d,"layout")); break;
                case "game_bounds": Manager.FollowGame(d); break;
                case "collapse":
                    bool returned=GameFocus.Return(Data.Object(d,"game")); Manager.Collapse();
                    Send("collapse_result","returned",returned && GameFocus.OwnsForeground(Data.Object(d,"game")),"game_pid",Data.Number(Data.Object(d,"game"),"pid")); break;
                case "game_state": Manager.RenderTask(d); break;
                case "game_show": ShowSurface("manager"); Manager.ShowPage(Data.Text(d,"page","inventory")); break;
                case "game_confirm": GameConfirm(d); break;
                case "lookup_state": Lookup.Render(d); break;
                case "settings_state": Settings.Render(d); break;
                case "plans": Plans.Render(d); ShowSurface("plans"); break;
                case "focus_search": ShowSurface("lookup"); Lookup.FocusSearch(); break;
                case "name_plan": NamePlan(d); break;
                case "game_name_plan": GameNamePlan(d); break;
                case "confirm": Confirm(d); break;
                case "exit_request": ExitRequest(Data.Object(d,"state"),"",false); break;
                case "exit_save_error": ExitRequest(Data.Object(d,"state"),Data.Text(d,"message","草稿副本未能保存"),true); break;
                case "exit_cancelled": CancelExit(Data.Text(d,"request_id","")); break;
                case "exit_waiting": ExitWaiting(Data.Object(d,"state"),Data.Text(d,"message","正在等待退出确认。"),Data.Flag(d,"can_cancel")); break;
                case "exit_finished": CloseExitDialog(); Manager.Error(Data.Text(d,"message","最后备份结果尚未确认，请在下次启动核对退出回执。")); break;
                case "drafts": Drafts(d); break;
                case "raw_draft": RawDraft(d); break;
                case "recover_settings": RecoverSettings(d); break;
                case "error": Fail(Data.Text(d,"message","操作未完成")); break;
                case "shutdown": Shutdown(); return;
            }
        } catch(Exception e) { Fail("窗口操作未完成："+e.Message); } } }
        public void Fail(string message) { if(Manager!=null) Manager.Error(message); }
        public void VisibilityAll() {
            if(Manager==null) return;
            foreach(string surface in new[]{"manager","lookup","settings","plans"}) Send("visibility","surface",surface,"visible",Manager.IsVisible && (surface=="manager" || !Manager.Collapsed && Manager.Page==surface),"hwnd",Manager.Handle.ToInt64(),"collapsed",Manager.Collapsed);
        }
        public void ShowSurface(string surface) { Manager.Expand(); if(surface!="manager") Manager.ShowPage(surface); if(!Manager.IsVisible) Manager.Show(); if(Manager.WindowState==WindowState.Minimized) Manager.WindowState=WindowState.Normal; Manager.Activate(); VisibilityAll(); if(surface=="lookup") Lookup.FocusSearch(); }
        public void HideSurface(string surface) { if(surface=="lookup" || surface=="settings" || surface=="plans") Manager.Collapse(); else Manager.Hide(); VisibilityAll(); }
        void SetFrozen(bool value) { Manager.Editable.IsEnabled=!value; if(activeName!=null) activeName.Editable.IsEnabled=!value; }
        void CloseExitDialog() { var dialog=activeExit; activeExit=null; if(dialog!=null) dialog.CloseSilently(); }
        void CancelExit(string id) { if(!exitRequests.Cancel(id)) return; CloseExitDialog(); Frozen=false; SetFrozen(false); }
        Dialog Decision(string title,string message,string saveLabel="保存副本并载入",string discardLabel="放弃草稿并载入") { var dialog=new Dialog(Manager,title,460,350); dialog.Body.Children.Add(UI.Text(message)); dialog.Actions.Children.Add(UI.Button(saveLabel,delegate { dialog.Choose("saved"); },true)); dialog.Actions.Children.Add(UI.Button("返回编辑",delegate { dialog.Choose("cancel"); })); dialog.Actions.Children.Add(UI.Button(discardLabel,delegate { dialog.Choose("discard"); })); return dialog; }
        void ExitRequest(Dictionary<string,object> state,string error,bool retry) {
            string id=Data.Text(state,"id",""); if(retry ? !exitRequests.IsCurrent(id) : !exitRequests.Begin(id)) return; CloseExitDialog();
            Lookup.FlushEdit(); Settings.FlushEdit(); Manager.FlushTasks(); Frozen=true; SetFrozen(true);
            var lookup=Lookup.Raw(); var settings=Settings.Raw(); bool dirty=Lookup.Dirty || Settings.Dirty || Manager.TasksDirty || SaveDraft!=null || error.Length>0; string decision="clean";
            if(dirty) { var dialog=Decision("退出灯火",(error.Length>0 ? "保存副本未完成："+error+"\n原始草稿仍保留。\n" : "")+"当前工作区有未保存草稿。退出后将停止后台辅助与自动备份。保存副本会保留全部原始输入。","保存草稿并退出","放弃草稿并退出"); activeExit=dialog; try { dialog.ShowDialog(); decision=dialog.Decision; } finally { if(activeExit==dialog) activeExit=null; } }
            if(!exitRequests.IsCurrent(id)) return;
            Send("exit_decision","request_id",id,"decision",decision,"lookup",Lookup.Dirty || SaveDraft!=null ? (object)lookup : null,"settings",Settings.Dirty ? (object)settings : null,"game",Manager.TaskRaw());
            if(decision=="cancel") { CloseExitDialog(); Frozen=false; SetFrozen(false); } else ExitWaiting(state,"正在保存草稿副本或确认放弃；磁盘等待期间仍可取消退出。",true);
        }
        void ExitWaiting(Dictionary<string,object> state,string message,bool canCancel) {
            string id=Data.Text(state,"id",""); if(!exitRequests.IsCurrent(id)) return; CloseExitDialog();
            var dialog=new Dialog(Manager,"正在结束本次辅助",440,260); dialog.Body.Children.Add(UI.Text(message));
            bool cancelling=false; Action cancel=delegate { if(!canCancel || cancelling || !exitRequests.IsCurrent(id)) return; cancelling=true; dialog.Actions.IsEnabled=false; dialog.Body.Children.Clear(); dialog.Body.Children.Add(UI.Text("正在取消退出；原始输入仍保留。")); Send("exit_decision","request_id",id,"decision","cancel"); };
            var button=UI.Button("取消退出，返回编辑",cancel); button.IsEnabled=canCancel; dialog.Actions.Children.Add(button); dialog.Closing+=delegate(object sender,System.ComponentModel.CancelEventArgs e) { if(!dialog.Silent) { e.Cancel=true; cancel(); } }; activeExit=dialog; dialog.Show();
        }
        void Confirm(Dictionary<string,object> d) { Lookup.FlushEdit(); Settings.FlushEdit(); Manager.FlushTasks(); string surface=Data.Text(d,"surface","lookup"),purpose=Data.Text(d,"purpose","replace"); var dialog=Decision(Data.Text(d,"title","替换草稿"),Data.Text(d,"text","请核对当前草稿"),purpose=="settings_reload" ? "保存副本并重新读取" : "保存副本并载入",purpose=="settings_reload" ? "放弃修改并重新读取" : "放弃草稿并载入"); dialog.ShowDialog(); if(purpose=="game_replace") Send("game_action","page",Data.Text(d,"page","equipment"),"command","replace_decision","decision",dialog.Decision); else Send(purpose=="settings_reload" ? "settings_reload_decision" : "replace_decision","surface",surface,"decision",dialog.Decision); }
        void GameConfirm(Dictionary<string,object> d) { bool undo=Data.Flag(d,"undo"); var dialog=new Dialog(Manager,undo ? "核对撤回回档" : "核对恢复进度",480,480); dialog.Body.Children.Add(UI.Text(Data.Text(d,"text",""))); dialog.Actions.Children.Add(UI.Button(undo ? "已关闭游戏，确认撤回" : "已关闭游戏，确认恢复",delegate { dialog.Choose("restore"); },true)); dialog.Actions.Children.Add(UI.Button("取消",delegate { dialog.Choose("cancel"); })); if(dialog.ShowDialog()==true) Send("game_action","page","backups","command","backup_execute","token",Data.Text(d,"token","")); }
        void GameNamePlan(Dictionary<string,object> d) {
            string page=Data.Text(d,"page",""); var dialog=new NameDialog(Manager,d); activeName=dialog; activeNamePage=page;
            dialog.Changed=delegate { if(!Frozen) Manager.SetTaskPlanMetadata(page,dialog.PlanName,dialog.Note); };
            try { if(dialog.ShowDialog()==true && !Frozen) { Manager.SetTaskPlanMetadata(page,dialog.PlanName,dialog.Note); Send("game_action","page",page,"command",dialog.UpdateOriginal ? "update" : "save"); } }
            finally { activeName=null; activeNamePage=null; }
        }
        void NamePlan(Dictionary<string,object> d) {
            var dialog=new NameDialog(Manager,d); activeName=dialog; dialog.Changed=delegate { if(!Frozen) Send("save_dialog_edit","surface","lookup","pending_save",dialog.Dirty ? (object)dialog.Raw() : null); };
            try { if(dialog.ShowDialog()==true && !Frozen) Send("save_named","surface","lookup","name",dialog.PlanName,"note",dialog.Note,"update",dialog.UpdateOriginal); }
            finally { activeName=null; if(!Frozen && !stopping) Send("save_dialog_closed","surface","lookup","cancelled",dialog.DialogResult!=true); }
        }
        void Drafts(Dictionary<string,object> d) {
            var dialog=new Dialog(Manager,"未完成草稿",520,480); var archived=UI.Name(new CheckBox { Content="显示已归档", IsChecked=Data.Flag(d,"include_archived") },"显示已归档"); dialog.Body.Children.Add(archived); archived.Checked+=delegate { Send("list_drafts","include_archived",true); dialog.Close(); }; archived.Unchecked+=delegate { Send("list_drafts","include_archived",false); dialog.Close(); };
            foreach(object item in Data.Array(d,"rows")) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""); string title=Data.Text(row,"text",""); if(title.Length==0) { double savedAt; string when=Double.TryParse(Data.Text(row,"saved",""),out savedAt) && savedAt>=0 && savedAt<=32503680000 ? new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(savedAt).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz") : "保存时间不可用"; title=Data.Text(row,"label","未完成草稿")+" · "+when+(Data.Text(row,"state","active")=="archived" ? " · 已归档" : ""); } var block=new StackPanel { Margin=new Thickness(0,12,0,0) }; block.Children.Add(UI.Text(title)); string error=Data.Text(row,"error",""); if(error.Length>0) block.Children.Add(UI.Text(error,12,UI.Gold));
                string[] components=new string[Data.Array(row,"components").Length]; int n=0; foreach(object component in Data.Array(row,"components")) components[n++]=Convert.ToString(component);
                if(error.Length==0 && !Data.Flag(row,"raw_original")) { if(components.Length>1) { foreach(string component in components) { string selected=component; block.Children.Add(UI.Button("载入 "+selected,delegate { Send("load_draft","id",id,"component",selected); dialog.Close(); })); } } else block.Children.Add(UI.Button("载入草稿（不自动应用）",delegate { Send("load_draft","id",id,"component",components.Length==1 ? components[0] : null); dialog.Close(); })); }
                if(Data.Flag(row,"raw_original") && error.Length==0) block.Children.Add(UI.Button("核对及获取原始文件",delegate { Send("inspect_raw_draft","id",id,"expected_revision",Data.Text(row,"state_revision","")); dialog.Close(); }));
                if(Data.Flag(row,"raw_preservable")) block.Children.Add(UI.Button("保留原始文件并归档",delegate { var confirm=new Dialog(dialog,"保留原始文件",460,370); confirm.Body.Children.Add(UI.Text("此文件无法载入为表单。先独立保留原始文件、核验后移出未完成列表。\n位置："+Data.Text(row,"path","")+"\n"+Data.Text(row,"bytes","")+" 字节\nSHA-256："+Data.Text(row,"sha256",""))); confirm.Actions.Children.Add(UI.Button("确认保留并归档",delegate { confirm.Choose("yes"); })); confirm.Actions.Children.Add(UI.Button("取消",delegate { confirm.Choose("cancel"); })); if(confirm.ShowDialog()==true) { Send("preserve_raw_draft","id",id,"expected_revision",Data.Text(row,"state_revision",""),"confirmed",true,"include_archived",archived.IsChecked==true); dialog.Close(); } }));
                else if(error.Length==0 && !Data.Flag(row,"raw_original")) { bool isArchived=Data.Text(row,"state","active")=="archived"; block.Children.Add(UI.Button(isArchived ? "恢复到未完成列表" : "已处理，归档副本",delegate { Send("draft_state","id",id,"state",isArchived ? "active" : "archived","expected_revision",Data.Text(row,"state_revision",""),"include_archived",archived.IsChecked==true); dialog.Close(); })); } dialog.Body.Children.Add(block);
            }
            if(Data.Array(d,"rows").Length==0) dialog.Body.Children.Add(UI.Text("没有未完成草稿。",13,UI.Muted)); dialog.Actions.Children.Add(UI.Button("返回",delegate { dialog.Close(); })); dialog.ShowDialog();
        }
        void RawDraft(Dictionary<string,object> d) { var row=Data.Object(d,"original"); string path=Data.Text(row,"path",""); var dialog=new Dialog(Manager,"已核对的原始文件",500,360); dialog.Body.Children.Add(UI.Text("仅保留原始字节，不能载入为表单。\n来源："+Data.Text(row,"source_name","")+"\n位置："+path+"\n"+Data.Text(row,"bytes","")+" 字节\nSHA-256："+Data.Text(row,"sha256",""))); dialog.Actions.Children.Add(UI.Button("定位文件以复制取回",delegate { try { Process.Start(new ProcessStartInfo("explorer.exe","/select,\""+path+"\"") { UseShellExecute=true }); } catch(Exception e) { Fail("文件定位未完成："+e.Message+"；原始副本仍保留。"); } })); dialog.ShowDialog(); }
        void RecoverSettings(Dictionary<string,object> d) {
            Settings.FlushEdit(); var dialog=new Dialog(Manager,"核对找回的设置",500,520); dialog.Body.Children.Add(UI.Text(Data.Text(d,"text","载入后仍需另行保存。"))); var selections=new Dictionary<string,ComboBox>(); foreach(object item in Data.Array(d,"rows")) { var row=(Dictionary<string,object>)item; string key=Data.Text(row,"key",""); var combo=UI.Combo(Data.Text(row,"label",key),"保留当前值","找回草稿值"); if(Data.Flag(row,"original_available")) combo.Items.Add("恢复原保存值"); combo.SelectedIndex=Data.Flag(row,"conflict") ? 0 : 1; selections[key]=combo; dialog.Body.Children.Add(UI.Field(Data.Text(row,"label",key)+(Data.Flag(row,"conflict") ? " · 需要核对" : ""),combo,"原保存值："+Data.Text(row,"original","")+"\n当前保存值："+Data.Text(row,"current","")+"\n找回的原始输入："+Data.Text(row,"draft",""))); }
            dialog.Actions.Children.Add(UI.Button("按选择载入（尚未保存）",delegate { dialog.Choose("restore"); },true)); dialog.Actions.Children.Add(UI.Button("取消",delegate { dialog.Choose("cancel"); })); dialog.ShowDialog(); var choices=new Dictionary<string,object>(); foreach(var pair in selections) choices[pair.Key]=pair.Value.SelectedIndex==1 ? "draft" : pair.Value.SelectedIndex==2 ? "original" : "current"; Send("settings_recovery_decision","surface","settings","decision",dialog.Decision,"choices",choices);
        }
        void Shutdown() { if(stopping) return; stopping=true; timer.Stop(); CloseExitDialog(); if(activeName!=null) activeName.CloseSilently(); foreach(Window window in new List<Window>(Windows())) if(window!=Manager) window.Close(); Manager.CloseForShutdown(); outgoing.CompleteAdding(); Application.Current.Shutdown(); }
        IEnumerable<Window> Windows() { foreach(Window window in Application.Current.Windows) yield return window; }
    }

    sealed class NameDialog : Dialog {
        readonly TextBox name=UI.Edit("方案名称",80), note=UI.Edit("用户用途或假设备注",1200);
        readonly CheckBox update=UI.Name(new CheckBox { Content="更新原方案（保留名称与身份）" },"更新原方案（保留名称与身份）");
        readonly string baselineName, baselineNote;
        readonly bool baselineUpdate, recovered;
        public Action Changed;
        public UIElement Editable { get { return Body; } }
        public string PlanName { get { return name.Text; } } public string Note { get { return UI.Note(note.Text); } } public bool UpdateOriginal { get { return update.IsChecked==true; } }
        public bool Dirty { get { return recovered || PlanName!=baselineName || Note!=baselineNote || UpdateOriginal!=baselineUpdate; } }
        public Dictionary<string,object> Raw() { return Data.Map("name",PlanName,"note",Note,"update",UpdateOriginal); }
        public NameDialog(Window owner,Dictionary<string,object> d) : base(owner,"保存参考方案",440,400) {
            string initial=Data.Text(d,"name","参考方案"); bool existing=Data.Flag(d,"existing"); name.Text=existing ? initial+" 副本" : initial; note.Text=Data.Text(d,"note",""); note.AcceptsReturn=true; note.TextWrapping=TextWrapping.Wrap; note.MinHeight=100; update.IsEnabled=existing;
            Action toggled=delegate { name.IsReadOnly=UpdateOriginal; name.Text=UpdateOriginal ? initial : initial+" 副本"; }; update.Checked+=delegate { toggled(); }; update.Unchecked+=delegate { toggled(); };
            Body.Children.Add(UI.Field("方案名称",name)); Body.Children.Add(UI.Field("用户用途 / 假设备注（可选，未验证）",note)); Body.Children.Add(update); Actions.Children.Add(UI.Button("保存",delegate { if(name.Text.Trim().Length==0) { name.Focus(); return; } Choose("saved"); },true)); Actions.Children.Add(UI.Button("取消",delegate { Choose("cancel"); }));
            baselineName=PlanName; baselineNote=Note; baselineUpdate=UpdateOriginal; var pending=Data.Object(d,"pending_save"); recovered=pending.Count>0; if(recovered) { update.IsChecked=existing && Data.Flag(pending,"update"); name.Text=Data.Text(pending,"name",name.Text); note.Text=Data.Text(pending,"note",note.Text); }
            name.TextChanged+=delegate { if(Changed!=null) Changed(); }; note.TextChanged+=delegate { if(Changed!=null) Changed(); }; update.Checked+=delegate { if(Changed!=null) Changed(); }; update.Unchecked+=delegate { if(Changed!=null) Changed(); };
        }
    }
    static class Program {
        [STAThread] static void Main(string[] args) {
            if(args.Length==3 && args[0]=="--choose-directory" && (args[1]=="save" || args[1]=="backup") && args[2].Length<=1000) {
                new Thread(new ThreadStart(delegate { try { Console.OpenStandardInput().ReadByte(); } catch {} Environment.Exit(0); })) { IsBackground=true }.Start(); Forms.Application.EnableVisualStyles(); object result;
                try { using(var picker=new Forms.FolderBrowserDialog { Description=args[1]=="save" ? "选择包含 game1、game2 等文件夹的存档目录；选定后仍需保存设置" : "选择已有本地备份文件夹；选定后仍需预览并确认",ShowNewFolderButton=false }) { if(Directory.Exists(args[2])) picker.SelectedPath=args[2]; bool accepted=picker.ShowDialog()==Forms.DialogResult.OK; result=Data.Map("cancelled",!accepted,"path",accepted ? picker.SelectedPath : ""); } } catch(Exception e) { result=Data.Map("error",e.Message); }
                using(var output=new StreamWriter(Console.OpenStandardOutput(),new UTF8Encoding(false))) output.WriteLine(new JavaScriptSerializer().Serialize(result)); return;
            }
            if(args.Length!=1 || args[0].Length!=32) return;
            var app=new Application { ShutdownMode=ShutdownMode.OnExplicitShutdown }; using(var stream=typeof(Program).Assembly.GetManifestResourceStream("Denghuo.Theme.xaml")) app.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Load(stream));
            var helper=new Helper(args[0]); app.Run(); GC.KeepAlive(helper);
        }
    }
}
