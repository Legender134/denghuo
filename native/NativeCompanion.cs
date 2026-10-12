// Local standard-controls helper. Business rules and persistent records belong to Python.
// C# 4 syntax; compiled against explicit .NET Framework 4.0 reference assemblies.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Diagnostics;
using System.Runtime.Versioning;
using System.Runtime.InteropServices;

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

    sealed class Helper : ApplicationContext {
        const int MaxLine = 524288;
        readonly string session;
        readonly BlockingCollection<string> incoming = new BlockingCollection<string>(128);
        readonly BlockingCollection<string> outgoing = new BlockingCollection<string>(128);
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = MaxLine, RecursionLimit = 64 };
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        long request, revision;
        bool stopping;
        public bool Frozen;
        readonly ExitRequests exitRequests = new ExitRequests();
        Form activeExit;
        public ManagerForm Manager;
        public LookupForm Lookup;
        public SettingsForm Settings;
        public PlansForm Plans;
        NameForm activeName;
        public object SaveDraft { get { return activeName != null && activeName.Dirty ? (object)activeName.Raw() : null; } }
        public void CaptureSaveDraft(Dictionary<string, object> raw) {
            // A closed dialog has no new intent; Python retains failed saves until cancel or success.
            if (activeName != null) raw["pending_save"] = SaveDraft;
        }
        public Helper(string key) {
            session = key;
            Manager = new ManagerForm(this); Lookup = new LookupForm(this);
            Settings = new SettingsForm(this); Plans = new PlansForm(this);
            Manager.Mount("lookup", Lookup); Manager.Mount("settings", Settings); Manager.Mount("plans", Plans);
            foreach (BaseForm form in new BaseForm[] { Manager, Lookup, Settings, Plans }) { var handle = form.Handle; }
            Send("ready", "pid", Process.GetCurrentProcess().Id, "system_dpi", Manager.SystemDpi, "framework", Environment.Version.ToString());
            var read = new Thread(Read) { IsBackground = true, Name = "native-json-reader" }; read.Start();
            var write = new Thread(Write) { IsBackground = true, Name = "native-json-writer" }; write.Start();
            timer.Interval = 30; timer.Tick += delegate { Drain(); }; timer.Start();
        }
        public void Send(string action, params object[] pairs) {
            var value = Data.Map(pairs); value["version"] = 1; value["session"] = session;
            value["request"] = ++request; value["revision"] = revision; value["action"] = action;
            string line = json.Serialize(value);
            if (line.Length > MaxLine || !outgoing.TryAdd(line)) Fail("原生窗口暂时繁忙，草稿仍保留；请稍后重试。");
        }
        void Read() {
            try {
                using (var reader = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false, true), false, 4096)) {
                    var line = new StringBuilder(); int ch;
                    while ((ch = reader.Read()) >= 0 && !stopping) {
                        if (ch == '\n') { if (!incoming.TryAdd(line.ToString(), 500)) throw new IOException("原生输入队列已满"); line.Length = 0; }
                        else if (ch != '\r') { line.Append((char)ch); if (line.Length > MaxLine) throw new IOException("协议行超出限制"); }
                    }
                }
            } catch (Exception e) { Console.Error.WriteLine(e.Message); }
            incoming.TryAdd("{\"action\":\"eof\"}", 500);
        }
        void Write() {
            try { using (var writer = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false), 4096)) {
                writer.AutoFlush = true; foreach (string line in outgoing.GetConsumingEnumerable()) writer.WriteLine(line);
            }} catch (Exception e) { Console.Error.WriteLine(e.Message); }
        }
        void Drain() {
            string line;
            for (int i = 0; i < 48 && incoming.TryTake(out line); ++i) {
                try {
                    var d = json.Deserialize<Dictionary<string, object>>(line);
                    string action = Data.Text(d, "action", "");
                    if (action == "eof") { Shutdown(); return; }
                    if (Data.Number(d, "version") != 1 || Data.Text(d, "session", "") != session) throw new IOException("原生协议身份不匹配");
                    revision = Math.Max(revision, Data.Number(d, "revision"));
                    switch (action) {
                        case "show": ShowSurface(Data.Text(d, "surface", "manager")); break;
                        case "hide": HideSurface(Data.Text(d, "surface", "manager")); break;
                        case "minimize_manager": Manager.WindowState = FormWindowState.Minimized; break;
                        case "manager_state": Manager.Render(d); break;
                        case "window_layout": Manager.LayoutRestored = Data.Flag(d, "restored"); Manager.ApplyLayout(Data.Object(d, "layout")); break;
                        case "game_bounds": Manager.FollowGame(d); break;
                        case "collapse": Manager.Collapse(); break;
                        case "game_state": Manager.RenderTask(d); break;
                        case "game_show": Manager.Expand(); Manager.ShowPage(Data.Text(d, "page", "inventory")); if (!Manager.Visible) Manager.Show(); Manager.Activate(); break;
                        case "game_confirm": using (var dialog = new ActionForm("灯火 · 核对恢复进度", Data.Text(d, "text", ""))) { if (dialog.ShowDialog(Manager) == DialogResult.OK) Send("game_action", "page", "backups", "command", "backup_execute", "token", Data.Text(d, "token", "")); } break;
                        case "lookup_state": Lookup.Render(d); break;
                        case "settings_state": Settings.Render(d); break;
                        case "plans": Plans.Render(d); if (!Plans.Visible) ShowSurface("plans"); break;
                        case "focus_search": ShowSurface("lookup"); Lookup.FocusSearch(); break;
                        case "name_plan": NamePlan(d); break;
                        case "confirm": Confirm(d); break;
                        case "exit_request": ExitRequest(Data.Object(d, "state")); break;
                        case "exit_save_error": ExitRequest(Data.Object(d, "state"), Data.Text(d, "message", "草稿副本未能保存"), true); break;
                        case "exit_cancelled": CancelExit(Data.Text(d, "request_id", "")); break;
                        case "exit_waiting": ExitWaiting(Data.Object(d, "state"), Data.Text(d, "message", "正在等待退出确认。"), Data.Flag(d, "can_cancel")); break;
                        case "exit_finished": CloseExitDialog(); Manager.Status.Text = Data.Text(d, "message", "最后备份结果尚未确认，请在下次启动核对退出回执。"); break;
                        case "drafts": Drafts(d); break;
                        case "raw_draft": RawDraft(d); break;
                        case "recover_settings": RecoverSettings(d); break;
                        case "error": Fail(Data.Text(d, "message", "原生操作未完成")); break;
                        case "shutdown": Shutdown(); return;
                    }
                } catch (Exception e) { Fail("窗口操作未完成：" + e.Message); }
            }
        }
        public void Fail(string message) { Manager.Status.Text = message; if (Manager.Visible) Manager.Status.Focus(); else MessageBox.Show(message, "灯火 · 操作未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
        public void Visibility(BaseForm form) { bool embedded = form == Lookup || form == Settings || form == Plans; Send("visibility", "surface", form.Surface, "visible", embedded ? Manager.Visible && !Manager.Collapsed && Manager.Page == form.Surface : form.Visible, "hwnd", embedded ? Manager.Handle.ToInt64() : form.Handle.ToInt64(), "collapsed", Manager != null && Manager.Collapsed); }
        public void ShowSurface(string surface) {
            if (surface == "manager" || surface == "lookup" || surface == "settings" || surface == "plans") {
                Manager.Expand(); if (surface != "manager") Manager.ShowPage(surface);
                if (!Manager.Visible) Manager.Show(); if (Manager.WindowState == FormWindowState.Minimized) Manager.WindowState = FormWindowState.Normal;
                Manager.Activate(); Visibility(Manager); Visibility(Lookup); Visibility(Settings); Visibility(Plans);
                if (surface == "lookup") Lookup.FocusSearch(); return;
            }
            BaseForm form = surface == "lookup" ? (BaseForm)Lookup : surface == "settings" ? (BaseForm)Settings : surface == "plans" ? (BaseForm)Plans : (BaseForm)Manager;
            if (!form.Visible) form.Show(); if (form.WindowState == FormWindowState.Minimized) form.WindowState = FormWindowState.Normal;
            form.Activate(); Visibility(form); if (surface == "lookup") Lookup.FocusSearch();
        }
        public void HideSurface(string surface) {
            if (surface == "lookup" || surface == "settings" || surface == "plans") { Manager.Collapse(); Visibility(Lookup); Visibility(Settings); Visibility(Plans); return; }
            BaseForm form = surface == "lookup" ? (BaseForm)Lookup : surface == "settings" ? (BaseForm)Settings : surface == "plans" ? (BaseForm)Plans : (BaseForm)Manager;
            form.Hide(); Visibility(form); if (surface == "plans" && Lookup.Visible) Lookup.Activate();
        }
        void SetFrozen(bool freeze) { Manager.Editable.Enabled = !freeze; Lookup.Editable.Enabled = !freeze; Settings.Editable.Enabled = !freeze; Plans.Enabled = !freeze; if (activeName != null) activeName.Editable.Enabled = !freeze; }
        void CloseExitDialog() { var dialog = activeExit; activeExit = null; var waiting = dialog as ExitWaitForm; if (waiting != null) waiting.CloseSilently(); else if (dialog != null) dialog.Close(); }
        void CancelExit(string id) {
            if (!exitRequests.Cancel(id)) return;
            CloseExitDialog(); Frozen = false; SetFrozen(false);
        }
        void ExitRequest(Dictionary<string, object> state, string error = "", bool retry = false) {
            string id = Data.Text(state, "id", "");
            if (retry ? !exitRequests.IsCurrent(id) : !exitRequests.Begin(id)) return;
            CloseExitDialog();
            Lookup.FlushEdit(); Settings.FlushEdit(); Manager.FlushTasks();
            Frozen = true; SetFrozen(true);
            var lookup = Lookup.Raw(); var settings = Settings.Raw();
            bool dirty = Lookup.Dirty || Settings.Dirty || Manager.TasksDirty || SaveDraft != null || error.Length > 0;
            string decision = "clean";
            if (dirty) {
                using (var dialog = new DecisionForm("退出灯火", (error.Length > 0 ? "保存副本未完成：" + error + "\n原始草稿仍保留。\n" : "") + "当前工作区有未保存草稿。保存副本会保留全部原始输入；取消可返回继续编辑。")) {
                    activeExit = dialog;
                    try {
                        dialog.ShowDialog(Manager.Visible ? (IWin32Window)Manager : Lookup.Visible ? (IWin32Window)Lookup : (IWin32Window)Settings);
                        decision = dialog.Decision;
                    } finally { if (activeExit == dialog) activeExit = null; }
                }
            }
            if (!exitRequests.IsCurrent(id)) return;
            Send("exit_decision", "request_id", id, "decision", decision, "lookup", Lookup.Dirty || SaveDraft != null ? (object)lookup : null, "settings", Settings.Dirty ? (object)settings : null, "game", Manager.TaskRaw());
            if (decision == "cancel") { CloseExitDialog(); Frozen = false; SetFrozen(false); }
            else ExitWaiting(state, "正在保存草稿副本或确认放弃；磁盘等待期间仍可取消退出。", true);
        }
        void ExitWaiting(Dictionary<string, object> state, string message, bool canCancel) {
            string id = Data.Text(state, "id", "");
            if (!exitRequests.IsCurrent(id)) return;
            var existing = activeExit as ExitWaitForm;
            if (existing != null) { existing.SetProgress(message, canCancel); return; }
            CloseExitDialog();
            var dialog = new ExitWaitForm(message, canCancel, delegate {
                if (exitRequests.IsCurrent(id)) Send("exit_decision", "request_id", id, "decision", "cancel");
            });
            activeExit = dialog;
            dialog.Show(Manager.Visible ? (IWin32Window)Manager : Lookup.Visible ? (IWin32Window)Lookup : (IWin32Window)Settings);
        }
        void Confirm(Dictionary<string, object> d) {
            Lookup.FlushEdit(); Settings.FlushEdit();
            string surface = Data.Text(d, "surface", "lookup"), purpose = Data.Text(d, "purpose", "replace");
            using (var dialog = new DecisionForm(Data.Text(d, "title", "替换草稿"), Data.Text(d, "text", "请确认当前草稿"))) {
                dialog.ShowDialog(Manager);
                Send(purpose == "settings_reload" ? "settings_reload_decision" : "replace_decision", "surface", surface, "decision", dialog.Decision);
            }
        }
        void NamePlan(Dictionary<string, object> d) {
            using (var dialog = new NameForm(Data.Text(d, "name", "参考方案"), Data.Text(d, "note", ""), Data.Flag(d, "existing"), Data.Object(d, "pending_save"))) {
                activeName = dialog;
                dialog.Changed = delegate { if (!Frozen) Send("save_dialog_edit", "surface", "lookup", "pending_save", dialog.Dirty ? (object)dialog.Raw() : null); };
                try { if (dialog.ShowDialog(Manager) == DialogResult.OK && !Frozen)
                    Send("save_named", "surface", "lookup", "name", dialog.PlanName, "note", dialog.Note, "update", dialog.UpdateOriginal);
                } finally { activeName = null; if (!Frozen && !stopping) Send("save_dialog_closed", "surface", "lookup", "cancelled", dialog.DialogResult != DialogResult.OK); }
            }
        }
        void Drafts(Dictionary<string, object> d) {
            using (var form = new BaseForm(this, "drafts", "灯火 · 会话草稿副本", 720, 440)) {
                form.TopMost = true;
                var table = UI.Table(1); table.Dock = DockStyle.Fill;
                var list = UI.List("未完成草稿副本列表"); list.Dock = DockStyle.Fill;
                var draftRows = new Dictionary<string, Dictionary<string, object>>();
                foreach (object item in Data.Array(d, "rows")) {
                    var row = (Dictionary<string, object>)item; string kind = Data.Text(row, "draft_kind", ""); string surface = kind == "numeric" ? "数值速查" : kind == "play-settings" ? "游玩设置" : kind == "offline-native" ? "离线原生副本" : kind == "game-workspace" ? "游戏工作区" : "完整面板";
                    double savedAt; string when = Double.TryParse(Data.Text(row, "saved", ""), out savedAt) && savedAt >= 0 && savedAt <= 32503680000 ? new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(savedAt).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss") : "保存时间不可用";
                    draftRows[Data.Text(row, "id", "")] = row;
                    string text = (Data.Text(row, "state", "active") == "archived" ? "[已归档] " : "[未完成] ") + Data.Text(row, "label", "无法读取的草稿") + " · " + surface + " · " + when + " · " + Data.Text(row, "id", "").Substring(0, 12); string error = Data.Text(row, "error", "");
                    object[] components = Data.Array(row, "components");
                    if (kind == "offline-native" && components.Length > 0 && error.Length == 0) {
                        foreach (object part in components) { string component = Convert.ToString(part); list.Items.Add(new Choice(Data.Text(row, "id", ""), text + " · 载入" + (component == "numeric" ? "数值表单" : component == "game-workspace" ? "游戏工作区" : "游玩设置表单"), component)); }
                    } else list.Items.Add(new Choice(Data.Text(row, "id", ""), text + (error.Length > 0 ? " · " + error : "")));
                }
                var open = UI.Button("载入所选草稿（不自动应用）", delegate { var choice = list.SelectedItem as Choice; if (choice != null) { Send("load_draft", "id", choice.Id, "component", choice.Component); form.CloseForShutdown(); } });
                var archived = UI.Name(new CheckBox { Text = "显示已归档", AutoSize = true }, "显示已归档"); archived.Checked = Data.Flag(d, "include_archived");
                archived.CheckedChanged += delegate { Send("list_drafts", "include_archived", archived.Checked); form.CloseForShutdown(); };
                var inspect = UI.Button("核对及获取原始文件", delegate { var choice = list.SelectedItem as Choice; if (choice == null) return; var row = draftRows[choice.Id]; Send("inspect_raw_draft", "id", choice.Id, "expected_revision", Data.Text(row, "state_revision", "")); form.CloseForShutdown(); });
                var archive = UI.Button("已处理，归档副本", delegate {
                    var choice = list.SelectedItem as Choice; if (choice == null) return; var row = draftRows[choice.Id];
                    if (Data.Flag(row, "raw_preservable")) {
                        string details = "此文件无法载入为表单。确认先独立保留原始文件、核验后移出未完成列表？\n位置：" + Data.Text(row, "path", "") + "\n" + Data.Text(row, "bytes", "") + " 字节\nSHA-256：" + Data.Text(row, "sha256", "") + "\n保留后可勾选「显示已归档」核对和获取。";
                        if (MessageBox.Show(form, details, "灯火 · 保留原始文件", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
                        Send("preserve_raw_draft", "id", choice.Id, "expected_revision", Data.Text(row, "state_revision", ""), "confirmed", true, "include_archived", archived.Checked);
                    } else {
                        if (Data.Text(row, "error", "").Length > 0 || Data.Flag(row, "raw_original")) return;
                        Send("draft_state", "id", choice.Id, "state", Data.Text(row, "state", "active") == "archived" ? "active" : "archived", "expected_revision", Data.Text(row, "state_revision", ""), "include_archived", archived.Checked);
                    }
                    form.CloseForShutdown();
                });
                list.SelectedIndexChanged += delegate {
                    var choice = list.SelectedItem as Choice; if (choice == null) { open.Enabled = archive.Enabled = inspect.Enabled = false; return; }
                    var row = draftRows[choice.Id]; bool raw = Data.Flag(row, "raw_original"), readable = Data.Text(row, "error", "").Length == 0;
                    open.Enabled = readable && !raw; archive.Enabled = !raw && (readable || Data.Flag(row, "raw_preservable")); inspect.Enabled = raw && readable;
                    archive.Text = Data.Flag(row, "raw_preservable") ? "保留原始文件并归档" : Data.Text(row, "state", "active") == "archived" ? "恢复到未完成列表" : "已处理，归档副本"; archive.AccessibleName = archive.Text;
                };
                table.RowCount = 4; table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                table.Controls.Add(archived, 0, 0); table.Controls.Add(list, 0, 1); table.Controls.Add(UI.Label("完整草稿可恢复。无法核对的文件仅保留原始字节，可核对和获取，不能载入为表单。"), 0, 2); table.Controls.Add(UI.Buttons(open, archive, inspect), 0, 3); form.Controls.Add(table);
                open.Enabled = archive.Enabled = inspect.Enabled = false;
                if (list.Items.Count > 0) list.SelectedIndex = 0;
                form.ShowDialog(Manager);
            }
        }
        void RawDraft(Dictionary<string, object> d) {
            var row = Data.Object(d, "original"); string path = Data.Text(row, "path", "");
            using (var form = new BaseForm(this, "drafts", "灯火 · 已核对的原始文件", 720, 360)) {
                var table = UI.Table(1); table.Dock = DockStyle.Fill;
                var details = UI.Name(new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, Dock = DockStyle.Fill, Text = "仅保留原始字节，不能载入为表单。\r\n来源：" + Data.Text(row, "source_name", "") + "\r\n位置：" + path + "\r\n" + Data.Text(row, "bytes", "") + " 字节\r\nSHA-256：" + Data.Text(row, "sha256", "") }, "原始文件核对结果");
                var locate = UI.Button("定位原始文件以复制取回", delegate { try { Process.Start(new ProcessStartInfo("explorer.exe", "/select,\"" + path + "\"") { UseShellExecute = true }); } catch (Exception e) { MessageBox.Show(form, "文件定位未完成：" + e.Message + "\n原始副本仍保留。", "灯火 · 原始文件", MessageBoxButtons.OK, MessageBoxIcon.Warning); } });
                table.RowCount = 2; table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.Controls.Add(details, 0, 0); table.Controls.Add(UI.Buttons(locate), 0, 1); form.Controls.Add(table); form.ShowDialog(Manager);
            }
        }
        void RecoverSettings(Dictionary<string, object> d) {
            Settings.FlushEdit();
            using (var dialog = new RecoveryForm(d)) {
                dialog.ShowDialog(Manager);
                Send("settings_recovery_decision", "surface", "settings", "decision", dialog.Decision,
                    "choices", dialog.Choices);
            }
        }
        void Shutdown() { stopping = true; timer.Stop(); foreach (BaseForm f in new BaseForm[] { Manager, Lookup, Settings, Plans }) f.CloseForShutdown(); outgoing.CompleteAdding(); ExitThread(); }
    }

    sealed class LampCombo : ComboBox {
        public LampCombo() { DrawMode = DrawMode.OwnerDrawFixed; DrawItem += delegate(object sender, DrawItemEventArgs e) { if (e.Bounds.Width <= 0) return; bool selected = (e.State & DrawItemState.Selected) != 0; using (var brush = new SolidBrush(selected ? UI.Border : UI.Panel)) e.Graphics.FillRectangle(brush, e.Bounds); string text = e.Index >= 0 && e.Index < Items.Count ? Items[e.Index].ToString() : Text; TextRenderer.DrawText(e.Graphics, text, Font, new Rectangle(e.Bounds.X+7, e.Bounds.Y, e.Bounds.Width-10, e.Bounds.Height), UI.Text, TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix); }; }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); ItemHeight = Font.Height+9; }
        protected override void WndProc(ref Message message) { base.WndProc(ref message); if (message.Msg == 15 && IsHandleCreated) { using (Graphics graphics = CreateGraphics()) { var area = new Rectangle(Width-22, 0, 22, Height); using (var brush = new SolidBrush(UI.Border)) graphics.FillRectangle(brush, area); using (var pen = new Pen(UI.Muted, 1.5F)) { int x = Width-12, y = Height/2; graphics.DrawLines(pen, new[] {new Point(x-4, y-2), new Point(x, y+2), new Point(x+4, y-2)}); } } } }
    }

    sealed class LampMenuRenderer : ToolStripProfessionalRenderer {
        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) { using (var brush = new SolidBrush(e.Item.Selected ? UI.Border : UI.Panel)) e.Graphics.FillRectangle(brush, new Rectangle(Point.Empty, e.Item.Size)); }
        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) { }
        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e) { e.TextColor = e.Item.Enabled ? UI.Text : UI.Muted; base.OnRenderItemText(e); }
    }

    static class UI {
        public static readonly Color Background = ColorTranslator.FromHtml("#121715"), Panel = ColorTranslator.FromHtml("#1a211d"), Border = ColorTranslator.FromHtml("#2c352f"), Text = ColorTranslator.FromHtml("#e9ede5"), Muted = ColorTranslator.FromHtml("#93a397"), Gold = ColorTranslator.FromHtml("#dec38c");
        public static void Theme(Control control) {
            control.BackColor = control is TextBoxBase || control is ListBox || control is TreeView ? Panel : Background; control.ForeColor = Text;
            var button = control as Button; if (button != null) { button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderSize = 0; button.FlatAppearance.MouseOverBackColor = Border; button.FlatAppearance.MouseDownBackColor = ColorTranslator.FromHtml("#39473b"); button.BackColor = Panel; button.Padding = new Padding(8, 3, 8, 3); button.Cursor = Cursors.Hand; }
            var combo = control as ComboBox; if (combo != null) { combo.FlatStyle = FlatStyle.Flat; combo.BackColor = Panel; }
            var list = control as ListBox; if (list != null) list.BorderStyle = BorderStyle.None;
            var read = control as RichTextBox; if (read != null) read.BorderStyle = BorderStyle.None;
            var tree = control as TreeView; if (tree != null) { tree.BorderStyle = BorderStyle.None; tree.LineColor = Border; tree.ShowLines = false; tree.ItemHeight = Math.Max(26, tree.Font.Height + 9); }
            foreach (Control child in control.Controls) Theme(child);
        }
        public static T Name<T>(T control, string name) where T : Control { control.AccessibleName = name; control.Name = name; control.Margin = new Padding(5); Theme(control); return control; }
        public static Label Label(string text) { var label = Name(new Label { Text = text, AutoSize = true, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, TabStop = false }, text); label.AccessibleName = null; return label; }
        public static TextBox Edit(string name) { return Name(new TextBox { Dock = DockStyle.Fill }, name); }
        public static RichTextBox Read(string name) { return Name(new RichTextBox { ReadOnly = true, Enabled = true, TabStop = true, Dock = DockStyle.Fill, WordWrap = true, DetectUrls = false, BorderStyle = BorderStyle.FixedSingle }, name); }
        public static ListBox List(string name) { return Name(new ListBox { IntegralHeight = false, HorizontalScrollbar = true, Dock = DockStyle.Fill }, name); }
        public static Button Button(string label, EventHandler clicked) { var b = Name(new Button { Text = label, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(0, 30), Dock = DockStyle.Fill }, label.Replace("&", "")); b.Click += clicked; return b; }
        public static TableLayoutPanel Table(int cols) { var table = new TableLayoutPanel { ColumnCount = cols, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(7) }; for (int i = 0; i < cols; ++i) table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / cols)); return table; }
        public static ComboBox Combo(string name, string[] choices) { var c = Name(new LampCombo { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill }, name); c.Items.AddRange(choices); if (choices.Length > 0) c.SelectedIndex = 0; return c; }
        public static ContextMenuStrip Menu() { return new ContextMenuStrip { Renderer = new LampMenuRenderer(), BackColor = Panel, ForeColor = Text, Font = new Font("Microsoft YaHei UI", 10F) }; }
        public static FlowLayoutPanel Buttons(params Control[] controls) { var panel = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true }; foreach (var control in controls) { control.Dock = DockStyle.None; panel.Controls.Add(control); } return panel; }
        public static void ReplaceText(RichTextBox field, string text) { if (field.Text == text) return; int start = field.SelectionStart, length = field.SelectionLength; field.Text = text; field.Select(Math.Min(start, field.TextLength), Math.Min(length, Math.Max(0, field.TextLength-start))); }
        public static void Article(RichTextBox field, string text) { if (field.Text == text) return; ReplaceText(field, text); int start = 0; foreach (string paragraph in text.Split(new[] {"\n\n"}, StringSplitOptions.None)) { int newline = paragraph.IndexOf('\n'); if (newline > 0) { field.Select(start, newline); field.SelectionColor = Gold; field.SelectionFont = new Font(field.Font.FontFamily, field.Font.Size+1, FontStyle.Bold); } start += paragraph.Length+2; } field.Select(0, 0); }
        public static string Note(string text) { return text.Replace("\r\n", "\n").Replace("\r", "\n"); }
        public static string Multiline(string text) { return Note(text).Replace("\n", "\r\n"); }
    }

    class BaseForm : Form {
        protected readonly Helper Host;
        public readonly string Surface;
        public Control Editable;
        public float SystemDpi;
        bool shutdown;
        public BaseForm(Helper host, string surface, string title, int width, int height) {
            Host = host; Surface = surface; Text = title; AccessibleName = title;
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            BackColor = UI.Background; ForeColor = UI.Text;
            Font = new Font("Microsoft YaHei UI", 10F); AutoScaleMode = AutoScaleMode.None;
            using (Graphics graphics = CreateGraphics()) SystemDpi = graphics.DpiX;
            float dpiScale = SystemDpi / 96F;
            Size = new Size((int)(width * dpiScale), (int)(height * dpiScale)); MinimumSize = new Size((int)(380 * dpiScale), (int)(300 * dpiScale));
            if (surface == "lookup" || surface == "settings" || surface == "plans") TopMost = true;
            StartPosition = FormStartPosition.CenterScreen; ShowInTaskbar = true; KeyPreview = true;
            Shown += delegate { DarkCaption(); Rectangle area = Screen.FromControl(this).WorkingArea; Size = new Size(Math.Min(Width, area.Width-20), Math.Min(Height, area.Height-20)); Host.Visibility(this); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (!shutdown && Surface != "drafts") { e.Cancel = true; if (Surface == "lookup") Host.Send("hide", "surface", "lookup"); else Host.HideSurface(Surface); } };
            KeyDown += delegate(object sender, KeyEventArgs e) {
                if (e.KeyCode == Keys.Escape && !Host.Frozen) { if (Surface == "drafts") CloseForShutdown(); else if (Surface == "manager") Host.Send("collapse"); else if (Surface == "lookup") Host.Send("hide", "surface", "lookup"); else Host.HideSurface(Surface); e.Handled = true; }
                else if (e.KeyCode == Keys.F1) { Host.Send("panel", "page", "help"); e.Handled = true; }
            };
        }
        public void CloseForShutdown() { shutdown = true; Close(); }
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int length);
        void DarkCaption() { try { int enabled = 1; if (DwmSetWindowAttribute(Handle, 20, ref enabled, 4) != 0) DwmSetWindowAttribute(Handle, 19, ref enabled, 4); } catch (DllNotFoundException) { } catch (EntryPointNotFoundException) { } }
    }

    sealed class LookupForm : BaseForm {
        readonly TextBox search = UI.Edit("搜索物品、敌人或技能");
        readonly ListBox rows = UI.List("搜索结果列表");
        readonly List<string> rowTokens = new List<string>();
        readonly TableLayoutPanel parameters = UI.Table(2);
        readonly Panel parameterScroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill };
        readonly RichTextBox result = UI.Read("数值结果与适用条件");
        readonly RichTextBox status = UI.Read("数值参数与保存状态");
        readonly TextBox note = UI.Edit("用户用途/假设备注（未验证）");
        readonly Dictionary<string, Control> edits = new Dictionary<string, Control>();
        readonly Dictionary<string, Label> labels = new Dictionary<string, Label>();
        readonly ToolStripMenuItem sources = new ToolStripMenuItem("官方依据");
        readonly ToolStripMenuItem undo = new ToolStripMenuItem("撤回本次参数导入");
        readonly ToolStripMenuItem latest = new ToolStripMenuItem("带入最新角色状态");
        readonly Button more;
        readonly Button conditions;
        readonly TableLayoutPanel outer = UI.Table(1);
        bool conditionsVisible, noteVisible;
        bool rendering, changed;
        long draftRevision;
        public bool Dirty;
        string fieldsSignature = "";
        public LookupForm(Helper host) : base(host, "lookup", "灯火 · 数值速查", 560, 740) {
            outer.Dock = DockStyle.Fill; outer.AutoSize = false; outer.Padding = new Padding(0); Editable = outer;
            var menu = new MenuStrip { Dock = DockStyle.Top }; var actions = new ToolStripMenuItem("资料操作(&O)");
            foreach (string[] pair in new string[][] { new[] { "收藏 / 取消收藏", "favorite" }, new[] { "保存 / 更新 / 另存方案", "save_plan" }, new[] { "打开已保存方案", "choose_plan" }, new[] { "重新读取当前方案", "reload_plan" }, new[] { "固定到游戏速查", "pin" }, new[] { "清除固定", "clear_pin" }, new[] { "来源与适用限制", "provenance" } }) {
                string action = pair[1]; var item = new ToolStripMenuItem(pair[0]); item.AccessibleName = pair[0]; item.Click += delegate { FlushEdit(); Host.Send(action, "surface", "lookup"); }; actions.DropDownItems.Add(item);
            }
            undo.Click += delegate { Host.Send("undo_import", "surface", "lookup"); }; actions.DropDownItems.Add(undo); actions.DropDownItems.Add(sources);
            latest.Click += delegate { FlushEdit(); Host.Send("use_latest", "surface", "lookup"); }; actions.DropDownItems.Add(latest);
            var panel = new ToolStripMenuItem("完整资料库"); panel.Click += delegate { Host.Send("panel", "page", "workspace"); }; actions.DropDownItems.Add(panel);
            foreach (string[] pair in new string[][] { new[] { "角色条件", "character" }, new[] { "装备比较", "equipment" }, new[] { "炼金规划", "alchemy" } }) {
                string page = pair[1]; var item = new ToolStripMenuItem(pair[0]); item.AccessibleName = pair[0]; item.Click += delegate { FlushEdit(); Host.Send("game_page", "page", page); Host.Manager.ShowPage(page); }; actions.DropDownItems.Add(item);
            }
            menu.Items.Add(actions); MainMenuStrip = menu;
            outer.RowCount = 7;
            outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, Font.Height*4+16)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, 0)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, 0)); outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, Font.Height*2+12));
            outer.Controls.Add(search, 0, 0); outer.Controls.Add(rows, 0, 1);
            more = UI.Button("显示更多结果", delegate { Host.Send("more", "surface", "lookup"); }); outer.Controls.Add(more, 0, 3);
            conditions = UI.Button("编辑条件 ▾", delegate { ToggleConditions(); });
            var calculate = UI.Button("计算", delegate { FlushEdit(); Host.Send("calculate", "surface", "lookup"); }); calculate.BackColor = UI.Gold; calculate.ForeColor = UI.Background;
            actions.DropDown.Renderer = new LampMenuRenderer(); actions.DropDown.BackColor = UI.Panel; actions.DropDown.ForeColor = UI.Text;
            outer.Controls.Add(UI.Buttons(calculate, conditions, more, UI.Button("资料 ⋯", delegate { actions.DropDown.Show(Cursor.Position); }), UI.Button("备注", delegate { noteVisible = !noteVisible; note.Visible = noteVisible; outer.RowStyles[4] = new RowStyle(SizeType.Absolute, noteVisible ? Font.Height*3+14 : 0); })), 0, 2);
            parameters.Dock = DockStyle.Top; parameterScroll.Controls.Add(parameters); parameterScroll.Visible = false; outer.Controls.Add(parameterScroll, 0, 3);
            note.Multiline = true; note.AcceptsReturn = true; note.ScrollBars = ScrollBars.Vertical; note.MaxLength = 1200; note.Visible = false; outer.Controls.Add(note, 0, 4);
            outer.Controls.Add(result, 0, 5); outer.Controls.Add(status, 0, 6); Controls.Add(outer);
            search.MaxLength = 200; search.TextChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("query", "surface", "lookup", "text", search.Text); };
            search.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { Host.Send("first", "surface", "lookup"); e.SuppressKeyPress = true; } else if (e.KeyCode == Keys.Down) { rows.Focus(); if (rows.Items.Count > 0 && rows.SelectedIndex < 0) rows.SelectedIndex = 0; e.SuppressKeyPress = true; } };
            rows.SelectedIndexChanged += delegate { if (!rendering && !Host.Frozen) SendSelection(); };
            rows.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter && rows.SelectedIndex >= 0) { SendSelection(); e.SuppressKeyPress = true; } };
            note.TextChanged += delegate { Edited(); };
            KeyDown += delegate(object sender, KeyEventArgs e) { if (e.Control && e.KeyCode == Keys.F) { FocusSearch(); e.SuppressKeyPress = true; } };
        }
        void ToggleConditions() { conditionsVisible = !conditionsVisible; parameterScroll.Visible = conditionsVisible; outer.RowStyles[3] = new RowStyle(conditionsVisible ? SizeType.Percent : SizeType.Absolute, conditionsVisible ? 50 : 0); conditions.Text = conditionsVisible ? "收起条件 ▴" : "编辑条件 ▾"; conditions.AccessibleName = conditionsVisible ? "收起条件" : "编辑条件"; }
        void Edited() { if (rendering || Host.Frozen) return; ++draftRevision; changed = Dirty = true; result.Text = "参数或备注已修改，请核对并重新计算。"; status.Text = "有未保存草稿。"; FlushEdit(); }
        public Dictionary<string, object> Raw() {
            var values = new Dictionary<string, object>(); foreach (var pair in edits) { var choice = pair.Value as ComboBox; values[pair.Key] = choice == null ? pair.Value.Text : ((Choice)choice.SelectedItem).Id; }
            var raw = Data.Map("values", values, "note", UI.Note(note.Text), "draft_revision", draftRevision);
            Host.CaptureSaveDraft(raw); return raw;
        }
        public void FlushEdit() { if (!changed) return; changed = false; var raw = Raw(); Host.Send("edit", "surface", "lookup", "values", raw["values"], "note", raw["note"], "draft_revision", draftRevision); }
        public void FocusSearch() { search.Focus(); search.SelectAll(); }
        void SendSelection() { int index = rows.SelectedIndex; if (index >= 0 && index < rowTokens.Count && !Host.Frozen) Host.Send("select", "surface", "lookup", "index", index, "token", rowTokens[index]); }
        public void Render(Dictionary<string, object> d) {
            if (Data.Number(d, "draft_revision") < draftRevision) return;
            rendering = true;
            try {
                draftRevision = Data.Number(d, "draft_revision"); Dirty = Data.Flag(d, "dirty"); latest.Enabled = Data.Flag(d, "can_latest");
                if (!search.Focused) search.Text = Data.Text(d, "query", "");
                int selected = rows.SelectedIndex; string old = selected >= 0 && selected < rowTokens.Count ? rowTokens[selected] : "";
                var texts = new List<string>(); var tokens = new List<string>(); foreach (object raw in Data.Array(d, "rows")) { var row = (Dictionary<string, object>)raw; texts.Add(Data.Text(row, "text", "")); tokens.Add(Data.Text(row, "token", "")); }
                string newRows = String.Join("\n", texts.ToArray()); var oldRows = new List<string>(); foreach (object item in rows.Items) oldRows.Add(Convert.ToString(item));
                if (newRows != String.Join("\n", oldRows.ToArray()) || String.Join("|", tokens.ToArray()) != String.Join("|", rowTokens.ToArray())) { rows.BeginUpdate(); rows.Items.Clear(); rows.Items.AddRange(texts.ToArray()); rowTokens.Clear(); rowTokens.AddRange(tokens); rows.SelectedIndex = old == "" ? -1 : rowTokens.IndexOf(old); rows.EndUpdate(); }
                rows.ItemHeight = Font.Height + 7; more.Enabled = Data.Flag(d, "can_more"); undo.Enabled = Data.Flag(d, "undo");
                var fields = Data.Array(d, "fields"); var keys = new List<string>(); foreach (object raw in fields) keys.Add(Data.Text((Dictionary<string, object>)raw, "key", ""));
                string signature = String.Join("|", keys.ToArray());
                if (signature != fieldsSignature) {
                    parameters.SuspendLayout(); parameters.Controls.Clear(); parameters.RowStyles.Clear(); edits.Clear(); labels.Clear(); parameters.RowCount = fields.Length; fieldsSignature = signature;
                    for (int i = 0; i < fields.Length; ++i) { var field = (Dictionary<string, object>)fields[i]; string key = Data.Text(field, "key", ""); string label = key == "corrosion_public" ? "酸蚀计算依据" : Data.Text(field, "label", key); Control text;
                        if (key == "corrosion_public") { var choice = UI.Combo(label, new string[0]); choice.Items.Add(new Choice("1", "游戏显示值（给范围）")); choice.Items.Add(new Choice("0", "手填精确假设")); choice.SelectedIndex = 0; choice.SelectedIndexChanged += delegate { Edited(); }; text = choice; }
                        else { var edit = UI.Edit(label); edit.MaxLength = 80; edit.TextChanged += delegate { Edited(); }; text = edit; }
                        text.AccessibleDescription = "来源与范围见相邻说明"; text.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { FlushEdit(); Host.Send("calculate", "surface", "lookup"); e.SuppressKeyPress = true; } };
                        text.Enter += delegate { parameterScroll.ScrollControlIntoView(text); };
                        var heading = UI.Label(label); edits[key] = text; labels[key] = heading; parameters.RowStyles.Add(new RowStyle(SizeType.AutoSize)); parameters.Controls.Add(heading, 0, i); parameters.Controls.Add(text, 1, i);
                    }
                    parameters.ResumeLayout(true);
                }
                foreach (object raw in fields) { var field = (Dictionary<string, object>)raw; string key = Data.Text(field, "key", ""); string text = Data.Text(field, "raw", ""); var choice = edits[key] as ComboBox;
                    if (choice != null) { int found = -1; for (int i = 0; i < choice.Items.Count; ++i) if (((Choice)choice.Items[i]).Id == text) found = i; if (found < 0) found = choice.Items.Add(new Choice(text, "需核对原始输入：" + text)); choice.SelectedIndex = found; }
                    else if (edits[key].Text != text) edits[key].Text = text;
                    labels[key].Text = (key == "corrosion_public" ? "酸蚀计算依据\n游戏显示值给范围；精确值仅为手填假设" : Data.Text(field, "label", key)) + "\n" + Data.Text(field, "origin", "") + (choice == null ? " · " + Data.Text(field, "min", "") + "–" + Data.Text(field, "max", "") : ""); edits[key].AccessibleDescription = labels[key].Text;
                }
                string noteText = UI.Multiline(Data.Text(d, "note", "")); if (note.Text != noteText) note.Text = noteText;
                UI.ReplaceText(result, Data.Text(d, "result", "")); UI.ReplaceText(status, Data.Text(d, "status", ""));
                conditions.Enabled = fields.Length > 0; if (fields.Length == 0 && conditionsVisible) ToggleConditions();
                sources.DropDownItems.Clear(); int index = 0; string sourcesToken = Data.Text(d, "sources_token", ""); foreach (object raw in Data.Array(d, "sources")) { var link = (Dictionary<string, object>)raw; int selectedLink = index++; var item = new ToolStripMenuItem(Data.Text(link, "label", "官方依据")); item.Click += delegate { Host.Send("source_link", "surface", "lookup", "index", selectedLink, "token", sourcesToken); }; sources.DropDownItems.Add(item); }
                sources.Enabled = sources.DropDownItems.Count > 0;
            } finally { rendering = false; }
        }
    }

    sealed class PlansForm : BaseForm {
        readonly TextBox search = UI.Edit("按方案名称或备注搜索");
        readonly ComboBox kind = UI.Combo("方案类型", new[] { "全部类型", "数值方案", "装备方案", "炼金方案", "手动草稿", "角色条件" });
        readonly ComboBox order = UI.Combo("方案排序", new[] { "最近更新", "名称" });
        readonly ListBox rows = UI.List("已保存方案列表：名称、类型、最近更新");
        readonly RichTextBox selected = UI.Read("所选方案完整名称、类型与日期");
        readonly Button open;
        bool rendering;
        public PlansForm(Helper host) : base(host, "plans", "灯火 · 打开已保存方案", 640, 450) {
            var table = UI.Table(1); table.Dock = DockStyle.Fill; Editable = table; table.RowCount = 6;
            table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.Absolute, 58)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            table.Controls.Add(UI.Label("数值、装备、炼金与角色方案在此工作区继续；手动局势在完整面板编辑。"), 0, 0); table.Controls.Add(search, 0, 1);
            var filters = UI.Table(4); filters.Dock = DockStyle.Fill; filters.Controls.Add(UI.Label("类型"), 0, 0); filters.Controls.Add(kind, 1, 0); filters.Controls.Add(UI.Label("排序"), 2, 0); filters.Controls.Add(order, 3, 0); table.Controls.Add(filters, 0, 2); table.Controls.Add(rows, 0, 3); table.Controls.Add(selected, 0, 4);
            open = UI.Button("打开所选方案(&O)", delegate { OpenSelected(); }); table.Controls.Add(open, 0, 5); Controls.Add(table);
            search.TextChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("filter_plans", "surface", "lookup", "query", search.Text, "kind", kind.Text, "order", order.Text); };
            foreach (ComboBox control in new ComboBox[] { kind, order }) { control.SelectedIndexChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("filter_plans", "surface", "lookup", "query", search.Text, "kind", kind.Text, "order", order.Text); }; }
            rows.SelectedIndexChanged += delegate { selected.Text = rows.SelectedItem == null ? "没有匹配方案" : rows.SelectedItem.ToString(); };
            rows.DoubleClick += delegate { OpenSelected(); }; rows.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { OpenSelected(); e.SuppressKeyPress = true; } };
            search.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Down) { rows.Focus(); e.SuppressKeyPress = true; } };
        }
        void OpenSelected() { var row = rows.SelectedItem as Choice; if (row != null) { Host.Send("open_plan", "surface", "lookup", "id", row.Id); } }
        public void Render(Dictionary<string, object> d) { rendering = true; var old = rows.SelectedItem as Choice; string id = old == null ? "" : old.Id; rows.BeginUpdate(); rows.Items.Clear(); int select = 0; foreach (object raw in Data.Array(d, "rows")) { var row = (Dictionary<string, object>)raw; var choice = new Choice(Data.Text(row, "id", ""), Data.Text(row, "text", "")); if (choice.Id == id) select = rows.Items.Count; rows.Items.Add(choice); } rows.ItemHeight = Font.Height + 8; if (rows.Items.Count > 0) rows.SelectedIndex = select; else selected.Text = "没有匹配方案；可更改搜索或类型。"; open.Enabled = rows.Items.Count > 0; rows.EndUpdate(); rendering = false; }
    }

    // A presentation surface only: public data, validation and saves remain in Python.
    sealed class ActionForm : Form {
        public ActionForm(string title, string message) { Text = title; AccessibleName = title; Font = new Font("Microsoft YaHei UI", 10F); Size = new Size(570, 430); StartPosition = FormStartPosition.CenterParent; MinimumSize = new Size(420, 300); TopMost = true;
            var table = UI.Table(1); table.AutoSize = false; table.Dock = DockStyle.Fill; table.RowCount = 2; table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); var text = UI.Read("当前与目标进度及恢复影响"); text.Text = message; table.Controls.Add(text, 0, 0); var cancel = UI.Button("取消", delegate { DialogResult = DialogResult.Cancel; }); table.Controls.Add(UI.Buttons(UI.Button("已关闭游戏，确认恢复", delegate { DialogResult = DialogResult.OK; }), cancel), 0, 1); Controls.Add(table); CancelButton = cancel; AcceptButton = cancel; UI.Theme(this);
        }
    }

    sealed class SavedMap : Control {
        Dictionary<string, object> data = new Dictionary<string, object>();
        public SavedMap() { DoubleBuffered = true; Dock = DockStyle.Top; Height = 200; AccessibleName = "主动揭示的保存地图：金色为角色，绿色为楼梯，浅灰为地面，深灰为墙"; }
        public void Render(Dictionary<string, object> value) { data = value; Visible = Data.Array(data, "tiles").Length > 0; Invalidate(); }
        protected override void OnPaint(PaintEventArgs e) { base.OnPaint(e); int width = (int)Data.Number(data, "width"), height = (int)Data.Number(data, "height"); object[] tiles = Data.Array(data, "tiles"); if (width < 1 || height < 1 || tiles.Length != width*height) return; float size = Math.Min((float)Width/width, (float)Height/height); float left = (Width-width*size)/2, top = (Height-height*size)/2; for (int i = 0; i < tiles.Length; ++i) { int tile = Convert.ToInt32(tiles[i]); Color color = tile == 4 || tile == 0 || tile == 23 ? UI.Border : tile == 7 || tile == 8 ? Color.FromArgb(91, 146, 105) : tile == 16 || tile == 17 ? UI.Gold : Color.FromArgb(100, 116, 104); if (data.ContainsKey("hero") && data["hero"] != null && Convert.ToInt32(data["hero"]) == i) color = UI.Gold; using (var brush = new SolidBrush(color)) e.Graphics.FillRectangle(brush, left+(i%width)*size, top+(i/width)*size, Math.Max(1, size-0.5f), Math.Max(1, size-0.5f)); } }
    }

    sealed class TaskPane : Panel {
        readonly Helper host; readonly string page;
        readonly TableLayoutPanel table = UI.Table(1), fields = UI.Table(1);
        readonly Panel scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        readonly RichTextBox result = UI.Read("结果、来源与适用条件");
        readonly SavedMap map = new SavedMap();
        readonly ListBox list = UI.List("工作区条目");
        readonly FlowLayoutPanel actions = UI.Buttons();
        readonly Button conditions;
        readonly Dictionary<string, Control> edits = new Dictionary<string, Control>();
        readonly Dictionary<string, bool> expanded = new Dictionary<string, bool>();
        Dictionary<string, object> values = new Dictionary<string, object>();
        readonly List<Dictionary<string, object>> rows = new List<Dictionary<string, object>>();
        string signature = ""; bool rendering; long revision;
        public bool Dirty;
        public TaskPane(Helper owner, string name) {
            host = owner; page = name; Dock = DockStyle.Fill; table.AutoSize = false; table.Dock = DockStyle.Fill; table.Padding = new Padding(0); table.RowCount = 5;
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 0)); table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.Absolute, 0)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            conditions = UI.Button("编辑条件 ▾", delegate { SetConditions(!scroll.Visible); });
            fields.Dock = DockStyle.Top; fields.Padding = new Padding(0); scroll.Controls.Add(fields); scroll.Visible = false;
            var output = new Panel { Dock = DockStyle.Fill }; output.Controls.Add(result); output.Controls.Add(map); map.Visible = false;
            table.Controls.Add(list, 0, 0); table.Controls.Add(output, 0, 1); table.Controls.Add(conditions, 0, 2); table.Controls.Add(scroll, 0, 3); table.Controls.Add(actions, 0, 4); Controls.Add(table);
            list.SelectedIndexChanged += delegate { if (!rendering && !host.Frozen && list.SelectedIndex >= 0 && list.SelectedIndex < rows.Count) { var row = rows[list.SelectedIndex]; host.Send("game_select", "page", page, "id", Data.Text(row, "id", ""), "token", Data.Text(row, "token", "")); } };
        }
        void SetConditions(bool show) { scroll.Visible = show; table.RowStyles[3] = new RowStyle(show ? SizeType.Percent : SizeType.Absolute, show ? 68 : 0); table.RowStyles[1] = new RowStyle(SizeType.Percent, show ? 32 : 100); conditions.Text = show ? "收起条件 ▴" : "编辑条件 ▾"; conditions.AccessibleName = show ? "收起条件" : "编辑条件"; }
        string Value(Control control) { var combo = control as ComboBox; if (combo != null) { var selected = combo.SelectedItem as Choice; return selected == null ? "" : selected.Id; } var check = control as CheckedListBox; if (check != null) { var selected = new List<string>(); foreach (Choice choice in check.CheckedItems) selected.Add(choice.Id); return String.Join("|", selected.ToArray()); } return control.Text; }
        public Dictionary<string, object> Raw() { var raw = new Dictionary<string, object>(values); foreach (var pair in edits) raw[pair.Key] = Value(pair.Value); return raw; }
        public void Flush() { if (edits.Count > 0) host.Send("game_edit", "page", page, "values", Raw(), "draft_revision", revision); }
        void Edited(string key, bool structural) { if (rendering || host.Frozen) return; ++revision; Dirty = true; values = Raw(); host.Send("game_edit", "page", page, "values", values, "draft_revision", revision, "structure", structural); if (key != "name" && key != "note") result.Text = "条件已修改，请重新计算。原始输入已保留。"; }
        public void Render(Dictionary<string, object> d) {
            if (Data.Number(d, "draft_revision") < revision) return;
            rendering = true;
            try {
                revision = Data.Number(d, "draft_revision"); Dirty = Data.Flag(d, "dirty"); values = new Dictionary<string, object>(Data.Object(d, "raw"));
                var specs = Data.Array(d, "fields"); var shape = new List<string>();
                foreach (object item in specs) { var spec = (Dictionary<string, object>)item; string key = Data.Text(spec, "key", ""); if (!values.ContainsKey(key)) values[key] = Data.Text(spec, "raw", ""); }
                foreach (object item in specs) { var spec = (Dictionary<string, object>)item; shape.Add(Data.Text(spec, "key", "") + Data.Text(spec, "label", "") + new JavaScriptSerializer().Serialize(Data.Array(spec, "choices"))); }
                string next = String.Join("\n", shape.ToArray());
                string focusedKey = null; int caret = 0; foreach (var pair in edits) if (pair.Value.ContainsFocus) { focusedKey = pair.Key; var editText = pair.Value as TextBox; if (editText != null) caret = editText.SelectionStart; }
                bool rebuilt = next != signature;
                if (next != signature) {
                    bool first = signature.Length == 0; Point position = scroll.AutoScrollPosition; fields.SuspendLayout(); var old = new List<Control>(); foreach (Control child in fields.Controls) old.Add(child); fields.Controls.Clear(); foreach (Control child in old) child.Dispose(); fields.RowStyles.Clear(); edits.Clear(); fields.RowCount = 0;
                    string section = ""; int n = 0, fieldRow = 0; TableLayoutPanel groupFields = null;
                    foreach (object item in specs) {
                        var spec = (Dictionary<string, object>)item; string group = Data.Text(spec, "section", "条件"), key = Data.Text(spec, "key", ""), label = Data.Text(spec, "label", key);
                        if (section != group) { section = group; groupFields = UI.Table(1); groupFields.Dock = DockStyle.Top; groupFields.Padding = new Padding(0); fieldRow = 0; bool open; if (!expanded.TryGetValue(group, out open)) open = group == "选择比较对象" || group == "共同条件" || group == "共享预算" || group.StartsWith("产出目标 1 ") || specs.Length < 12;
                            groupFields.Visible = open; expanded[group] = open; var target = groupFields; string name = group; Button title = null; title = UI.Button(group + (open ? " ▴" : " ▾"), delegate { bool show = !target.Visible; target.Visible = show; expanded[name] = show; title.Text = name + (show ? " ▴" : " ▾"); title.AccessibleName = (show ? "收起" : "展开") + name; }); title.AccessibleName = (open ? "收起" : "展开") + group; title.ForeColor = UI.Gold; title.TextAlign = ContentAlignment.MiddleLeft; title.Margin = new Padding(5, 8, 5, 2); fields.Controls.Add(title, 0, n++); fields.RowStyles.Add(new RowStyle(SizeType.AutoSize)); fields.Controls.Add(groupFields, 0, n++); fields.RowStyles.Add(new RowStyle(SizeType.AutoSize)); }
                        groupFields.Controls.Add(UI.Label(label), 0, fieldRow++); groupFields.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                        Control edit; object[] choices = Data.Array(spec, "choices");
                        if (Data.Flag(spec, "multiple")) { var multi = UI.Name(new CheckedListBox { Dock = DockStyle.Fill, CheckOnClick = true, Height = Font.Height * 5, BorderStyle = BorderStyle.None }, label); foreach (object option in choices) { var c = (Dictionary<string, object>)option; if (Data.Text(c, "id", "").Length > 0) multi.Items.Add(new Choice(Data.Text(c, "id", ""), Data.Text(c, "text", ""))); } multi.ItemCheck += delegate { if (!rendering) BeginInvoke((MethodInvoker)delegate { Edited(key, false); }); }; edit = multi; }
                        else if (choices.Length > 0) { var combo = UI.Combo(label, new string[0]); combo.DropDownWidth = Math.Max(320, Width); foreach (object option in choices) { var c = (Dictionary<string, object>)option; combo.Items.Add(new Choice(Data.Text(c, "id", ""), Data.Text(c, "text", ""))); } combo.SelectedIndexChanged += delegate { Edited(key, true); }; edit = combo; }
                        else { var text = UI.Edit(label); text.MaxLength = 1200; text.TextChanged += delegate { Edited(key, false); }; edit = text; }
                        edits[key] = edit; edit.Enter += delegate { scroll.ScrollControlIntoView(edit); }; groupFields.Controls.Add(edit, 0, fieldRow++); groupFields.RowCount = fieldRow; groupFields.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                    }
                    fields.RowCount = n; fields.ResumeLayout(true); signature = next; scroll.AutoScrollPosition = new Point(-position.X, -position.Y); if (first && specs.Length > 0) SetConditions(true);
                }
                conditions.Visible = specs.Length > 0;
                foreach (var pair in edits) {
                    string raw = Data.Text(values, pair.Key, ""); var combo = pair.Value as ComboBox; var multi = pair.Value as CheckedListBox;
                    if (combo != null) { int index = -1; for (int i = 0; i < combo.Items.Count; ++i) if (((Choice)combo.Items[i]).Id == raw) index = i; if (index < 0) { index = combo.Items.Add(new Choice(raw, "需核对的原始输入：" + raw)); } combo.SelectedIndex = index; }
                    else if (multi != null) { var selected = new HashSet<string>(raw.Split('|')); foreach (string value in selected) { bool found = value.Length == 0; foreach (Choice choice in multi.Items) if (choice.Id == value) found = true; if (!found) multi.Items.Add(new Choice(value, "需核对原始实例："+value)); } for (int i = 0; i < multi.Items.Count; ++i) multi.SetItemChecked(i, selected.Contains(((Choice)multi.Items[i]).Id)); }
                    else if (pair.Value.Text != raw) pair.Value.Text = raw;
                }
                if (rebuilt && focusedKey != null && edits.ContainsKey(focusedKey) && scroll.Visible) { Control focused = edits[focusedKey]; focused.Focus(); var editText = focused as TextBox; if (editText != null) editText.SelectionStart = Math.Min(caret, editText.TextLength); }
                int oldTop = list.TopIndex; rows.Clear(); list.BeginUpdate(); list.Items.Clear(); int selectedRow = -1; foreach (object item in Data.Array(d, "rows")) { var row = (Dictionary<string, object>)item; if (Data.Text(row, "id", "") == Data.Text(d, "selected", "")) selectedRow = rows.Count; rows.Add(row); list.Items.Add(Data.Text(row, "text", "")); } list.SelectedIndex = selectedRow; list.ItemHeight = Font.Height + 12; if (list.Items.Count > 0) list.TopIndex = Math.Min(oldTop, list.Items.Count-1); list.EndUpdate();
                table.RowStyles[0] = new RowStyle(rows.Count > 0 ? SizeType.Percent : SizeType.Absolute, rows.Count > 0 ? 40 : 0); list.Visible = rows.Count > 0;
                UI.ReplaceText(result, Data.Text(d, "text", ""));
                map.Render(Data.Object(d, "map"));
                var oldActions = new List<Control>(); foreach (Control child in actions.Controls) oldActions.Add(child); actions.Controls.Clear(); foreach (Control child in oldActions) child.Dispose();
                var extra = UI.Menu(); extra.BackColor = UI.Panel; extra.ForeColor = UI.Text;
                foreach (object item in Data.Array(d, "actions")) { var action = (Dictionary<string, object>)item; string command = Data.Text(action, "id", ""); EventHandler clicked = delegate { if (!host.Frozen) { Flush(); host.Send("game_action", "page", page, "command", command, "values", Raw(), "draft_revision", revision); } };
                    if (page == "alchemy" && (command.StartsWith("add_") || command.StartsWith("remove_") || command == "undo" || command == "update")) { var entry = extra.Items.Add(Data.Text(action, "text", "")); entry.Click += clicked; entry.Enabled = !Data.Flag(action, "disabled"); }
                    else { var button = UI.Button(Data.Text(action, "text", ""), clicked); button.Enabled = !Data.Flag(action, "disabled"); if (command == "calculate") { button.ForeColor = UI.Background; button.BackColor = UI.Gold; } actions.Controls.Add(button); } }
                if (extra.Items.Count > 0) { var more = UI.Button("更多操作 ⋯", delegate { extra.Show(Cursor.Position); }); more.Disposed += delegate { extra.Dispose(); }; actions.Controls.Add(more); } else extra.Dispose();
                if (Data.Flag(d, "focus_result")) SetConditions(false);
            } finally { rendering = false; }
        }
    }

    sealed class ManagerForm : BaseForm {
        readonly RichTextBox summary = UI.Read("当前存档、生命、风险、资源与备份全文");
        readonly Label life = UI.Label("等待有效存档"), statistics = UI.Label("保存游戏后会显示生命与局势");
        readonly TableLayoutPanel overview = UI.Table(1);
        public readonly RichTextBox Status = UI.Read("管理操作和快捷键实际状态");
        readonly ComboBox slot = UI.Combo("存档槽位", new[] { "自动跟随", "槽位 1", "槽位 2", "槽位 3", "槽位 4", "槽位 5", "槽位 6" });
        readonly CheckBox top = UI.Name(new CheckBox { Text = "管理窗口置顶", AutoSize = true }, "管理窗口置顶");
        readonly ListBox references = UI.List("风险与资源参考资料");
        readonly List<string> referenceTokens = new List<string>();
        readonly Panel options = new Panel { Dock = DockStyle.Fill, AutoSize = true, Visible = false };
        readonly List<Control> connectionControls = new List<Control>();
        readonly Button compact;
        readonly TreeView floor = UI.Name(new TreeView { Dock = DockStyle.Fill, HideSelection = false }, "本层隐藏内容与可折叠怪物数值及掉落资料");
        readonly RichTextBox floorDetail = UI.Read("所选楼层资料的完整条件与说明");
        readonly Label floorCaption = UI.Label("当前楼层");
        readonly Button revealFloor;
        string floorToken = "", floorSignature = "", floorOwner = "";
        bool rendering, attached; bool changingLayout = true;
        public bool Collapsed, LayoutRestored;
        public string Page = "overview";
        readonly Dictionary<string, Panel> pages = new Dictionary<string, Panel>();
        readonly Dictionary<string, Button> navigation = new Dictionary<string, Button>();
        readonly Dictionary<string, TaskPane> tasks = new Dictionary<string, TaskPane>();
        ContextMenuStrip mainMenu;
        public bool TasksDirty { get { foreach (TaskPane pane in tasks.Values) if (pane.Dirty) return true; return false; } }
        public Dictionary<string, object> TaskRaw() { var raw = new Dictionary<string, object>(); foreach (var pair in tasks) if (pair.Value.Dirty) raw[pair.Key] = pair.Value.Raw(); return raw; }
        public void FlushTasks() { foreach (TaskPane pane in tasks.Values) if (pane.Dirty) pane.Flush(); }
        public void RenderTask(Dictionary<string, object> d) { string page = Data.Text(d, "page", ""); if (tasks.ContainsKey(page)) tasks[page].Render(d); }
        readonly TableLayoutPanel workspace = UI.Table(1);
        readonly Panel content = new Panel { Dock = DockStyle.Fill };
        readonly Label source = UI.Label("等待游戏保存 · 自动备份守护中");
        readonly Button handle;
        Rectangle expandedBounds, gameBounds;
        int gameX = 16, gameY = 16;
        protected override bool ShowWithoutActivation { get { return true; } }
        public ManagerForm(Helper host) : base(host, "manager", "灯火 · 游戏助手", 480, 600) {
            MinimumSize = new Size(Pixels(320), Pixels(360)); expandedBounds = Bounds;
            workspace.Dock = DockStyle.Fill; workspace.AutoSize = false; Editable = workspace; workspace.Padding = new Padding(14);
            workspace.RowCount = 5;
            workspace.RowStyles.Add(new RowStyle(SizeType.AutoSize)); workspace.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            workspace.RowStyles.Add(new RowStyle(SizeType.AutoSize)); workspace.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); workspace.RowStyles.Add(new RowStyle(SizeType.Absolute, Font.Height * 2 + 14));
            compact = UI.Button("收起", delegate { Host.Send("collapse"); });
            var brand = UI.Label("灯火"); brand.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold); brand.ForeColor = UI.Gold;
            var heading = UI.Table(3); heading.Dock = DockStyle.Fill; heading.AutoSize = false; heading.Padding = new Padding(0); heading.ColumnStyles.Clear(); heading.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); heading.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); heading.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); heading.Controls.Add(brand, 0, 0); heading.Controls.Add(compact, 1, 0); heading.Controls.Add(UI.Button("更多 ⋯", delegate { ShowMore(); }), 2, 0);
            workspace.RowStyles[0] = new RowStyle(SizeType.Absolute, Pixels(48));
            workspace.Controls.Add(heading, 0, 0); source.ForeColor = UI.Muted; workspace.Controls.Add(source, 0, 1);
            var tabs = UI.Buttons(); tabs.Margin = new Padding(0, 7, 0, 10);
            foreach (string[] entry in new string[][] { new[] { "局势", "overview" }, new[] { "背包", "inventory" }, new[] { "数值", "lookup" }, new[] { "装备", "equipment" }, new[] { "炼金", "alchemy" }, new[] { "楼层", "floor" } }) { string page = entry[1]; var button = UI.Button(entry[0], delegate { OpenPage(page); }); navigation[page] = button; tabs.Controls.Add(button); }
            workspace.Controls.Add(tabs, 0, 2); workspace.Controls.Add(content, 0, 3); workspace.Controls.Add(Status, 0, 4);
            foreach (string page in new[] { "overview", "inventory", "lookup", "equipment", "alchemy", "character", "floor", "map", "backups", "plans", "settings" }) { var panel = new Panel { Dock = DockStyle.Fill, Visible = false }; pages[page] = panel; content.Controls.Add(panel); }
            foreach (string page in new[] { "inventory", "equipment", "alchemy", "character", "map", "backups" }) { var pane = new TaskPane(host, page); tasks[page] = pane; pages[page].Controls.Add(pane); }
            overview.AutoSize = false; overview.Dock = DockStyle.Fill; overview.Padding = new Padding(0); overview.RowCount = 6;
            overview.RowStyles.Add(new RowStyle(SizeType.AutoSize)); overview.RowStyles.Add(new RowStyle(SizeType.AutoSize)); overview.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); overview.RowStyles.Add(new RowStyle(SizeType.AutoSize)); overview.RowStyles.Add(new RowStyle(SizeType.Absolute, 60)); overview.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            life.Font = new Font(Font.FontFamily, 22F, FontStyle.Bold); life.ForeColor = UI.Gold; statistics.ForeColor = UI.Muted; statistics.Margin = new Padding(5, 0, 5, 16);
            summary.BackColor = UI.Background;
            overview.Controls.Add(life, 0, 0); overview.Controls.Add(statistics, 0, 1); overview.Controls.Add(summary, 0, 2); overview.Controls.Add(UI.Label("相关资料 · 双击查看"), 0, 3); overview.Controls.Add(references, 0, 4);
            overview.Controls.Add(UI.Buttons(UI.Button("立即备份", delegate { Host.Send("capture"); }), UI.Button("刷新存档", delegate { Host.Send("refresh"); }), UI.Button("找回草稿", delegate { Host.Send("list_drafts"); })), 0, 5); pages["overview"].Controls.Add(overview);
            var settings = UI.Table(2); settings.Dock = DockStyle.Top; settings.Controls.Add(UI.Label("存档槽位"), 0, 0); settings.Controls.Add(slot, 1, 0); settings.Controls.Add(top, 0, 1);
            var refresh = UI.Button("刷新", delegate { Host.Send("refresh"); }); settings.Controls.Add(refresh, 1, 1);
            var directory = UI.Button("选择存档目录…", delegate { using (var picker = new FolderBrowserDialog { Description = "选择包含 game1、game2 等文件夹的存档目录", ShowNewFolderButton = false }) { if (picker.ShowDialog(this) == DialogResult.OK) Host.Send("directory", "path", picker.SelectedPath); } }); settings.Controls.Add(directory, 0, 2);
            connectionControls.AddRange(new Control[] { slot, top, refresh, directory });
            settings.Controls.Add(UI.Button("恢复默认大小与位置", delegate { ResetLayout(); }), 1, 2); options.Controls.Add(settings); options.Visible = true; options.Dock = DockStyle.Top;
            var inspector = UI.Table(1); inspector.Dock = DockStyle.Fill; inspector.RowCount = 4;
            inspector.RowStyles.Add(new RowStyle(SizeType.AutoSize)); inspector.RowStyles.Add(new RowStyle(SizeType.AutoSize)); inspector.RowStyles.Add(new RowStyle(SizeType.Percent, 65)); inspector.RowStyles.Add(new RowStyle(SizeType.Percent, 35));
            revealFloor = UI.Button("揭示本层隐藏内容", delegate { Host.Send("reveal_floor", "token", floorToken); });
            var adjustFloor = UI.Button("查看所选资料数值…", delegate { AdjustFloorReference(); });
            inspector.Controls.Add(floorCaption, 0, 0); inspector.Controls.Add(UI.Buttons(revealFloor, adjustFloor), 0, 1); inspector.Controls.Add(floor, 0, 2); inspector.Controls.Add(floorDetail, 0, 3);
            floor.AfterSelect += delegate { if (floor.SelectedNode != null) UI.ReplaceText(floorDetail, FloorDetailText(floor.SelectedNode)); };
            pages["floor"].Controls.Add(inspector); Controls.Add(workspace);
            handle = UI.Button("灯\n›", delegate { if (!handleDragged) { Expand(); Activate(); } handleDragged = false; }); handle.AccessibleName = "展开灯火助手"; handle.ForeColor = UI.Gold; handle.Font = new Font(Font.FontFamily, 14F, FontStyle.Bold); handle.Dock = DockStyle.Fill; handle.Visible = false; Controls.Add(handle);
            handle.MouseDown += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) { dragOrigin = Cursor.Position; dragLocation = Location; handleDragged = false; } };
            handle.MouseMove += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) { Point current = Cursor.Position; if (Math.Abs(current.X-dragOrigin.X) + Math.Abs(current.Y-dragOrigin.Y) > 6) { handleDragged = true; Location = new Point(dragLocation.X+current.X-dragOrigin.X, dragLocation.Y+current.Y-dragOrigin.Y); } } };
            handle.MouseUp += delegate { if (handleDragged) { expandedBounds.Location = Location; ClampBounds(); SaveLayout(); } };
            ResizeEnd += delegate { if (!changingLayout && WindowState == FormWindowState.Normal) { if (!Collapsed) expandedBounds = Bounds; SaveLayout(); } };
            KeyDown += delegate(object sender, KeyEventArgs e) { if (e.Control && e.KeyCode == Keys.F && Page == "lookup") { Host.Lookup.FocusSearch(); e.SuppressKeyPress = true; } };
            ShowPage("overview");
            Disposed += delegate { if (mainMenu != null) mainMenu.Dispose(); };
            slot.SelectedIndexChanged += delegate { if (!rendering) Host.Send("slot", "index", slot.SelectedIndex); };
            top.CheckedChanged += delegate { if (!rendering) Host.Send("pin_manager", "checked", top.Checked); };
            references.DoubleClick += delegate { Reference(); }; references.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { Reference(); e.SuppressKeyPress = true; } };
        }
        Point dragOrigin, dragLocation;
        bool handleDragged;
        int Pixels(int value) { return (int)Math.Round(value * SystemDpi / 96F); }
        int Logical(int value) { return (int)Math.Round(value * 96F / SystemDpi); }
        public void Mount(string page, BaseForm form) {
            var body = new Panel { Dock = DockStyle.Fill }; var controls = new List<Control>(); foreach (Control child in form.Controls) controls.Add(child);
            foreach (Control child in controls) body.Controls.Add(child);
            if (page == "settings") { var shell = UI.Table(1); shell.AutoSize = false; shell.Dock = DockStyle.Fill; shell.RowCount = 2; shell.RowStyles.Add(new RowStyle(SizeType.AutoSize)); shell.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); shell.Controls.Add(options, 0, 0); shell.Controls.Add(body, 0, 1); pages[page].Controls.Add(shell); }
            else pages[page].Controls.Add(body);
        }
        void ShowMore() { if (mainMenu != null) mainMenu.Dispose(); var menu = mainMenu = UI.Menu(); foreach (string[] entry in new string[][] { new[] { "角色条件", "character" }, new[] { "地图", "map" }, new[] { "存档历史", "backups" }, new[] { "已保存方案", "plans" }, new[] { "设置", "settings" } }) { string page = entry[1]; var item = menu.Items.Add(entry[0]); item.Click += delegate { OpenPage(page); }; } menu.Items.Add("恢复默认大小与位置", null, delegate { ResetLayout(); }); menu.Items.Add("完整面板", null, delegate { Host.Send("panel", "page", "overview"); }); menu.Items.Add("退出灯火", null, delegate { Host.Send("exit"); }); menu.BackColor = UI.Panel; menu.ForeColor = UI.Text; menu.Show(this, PointToClient(Cursor.Position), ToolStripDropDownDirection.BelowLeft); }
        void OpenPage(string page) { if (page == "lookup") Host.Send("show_lookup"); else if (page == "settings") Host.Send("show_settings"); else if (page == "plans") { Host.Send("choose_plan", "surface", "lookup"); } else { ShowPage(page); if (page != "overview" && page != "floor") Host.Send("game_page", "page", page); } }
        public void ShowPage(string page) { if (!pages.ContainsKey(page)) return; Page = page; foreach (var pair in pages) pair.Value.Visible = pair.Key == page; foreach (var pair in navigation) { pair.Value.ForeColor = pair.Key == page ? UI.Gold : UI.Muted; pair.Value.BackColor = pair.Key == page ? UI.Border : UI.Panel; } Host.Visibility((BaseForm)Host.Lookup ?? this); if (!changingLayout) SaveLayout(); }
        void ClampBounds() { Rectangle area = Screen.FromRectangle(Bounds).WorkingArea; Width = Math.Min(Width, area.Width); Height = Math.Min(Height, area.Height); Left = Math.Max(area.Left, Math.Min(Left, area.Right-Width)); Top = Math.Max(area.Top, Math.Min(Top, area.Bottom-Height)); }
        public void Collapse() { if (Collapsed) return; changingLayout = true; expandedBounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds; WindowState = FormWindowState.Normal; Collapsed = true; workspace.Visible = false; MinimumSize = Size.Empty; FormBorderStyle = FormBorderStyle.None; Size = new Size(Pixels(44), Pixels(76)); handle.Visible = true; handle.BringToFront(); ShowInTaskbar = true; ClampBounds(); changingLayout = false; SaveLayout(); Host.Visibility(this); Host.Visibility(Host.Lookup); }
        public void Expand() { if (!Collapsed) return; changingLayout = true; handle.Visible = false; Collapsed = false; FormBorderStyle = FormBorderStyle.Sizable; MinimumSize = new Size(Pixels(320), Pixels(360)); Bounds = expandedBounds; workspace.Visible = true; ShowInTaskbar = true; ClampBounds(); changingLayout = false; SaveLayout(); Host.Visibility(this); Host.Visibility(Host.Lookup); }
        void SaveLayout(bool reset = false) { if (changingLayout) return; LayoutRestored = true; Rectangle normal = Collapsed ? expandedBounds : WindowState == FormWindowState.Normal ? Bounds : RestoreBounds; if (normal.Width < 100) return; if (attached) { gameX = Logical(Left-gameBounds.Left); gameY = Logical(Top-gameBounds.Top); }
            Host.Send(reset ? "layout_reset" : "window_layout", "layout", Data.Map("width", Math.Max(320, Logical(normal.Width)), "height", Math.Max(320, Logical(normal.Height)), "x", Logical(normal.Left), "y", Logical(normal.Top), "game_x", gameX, "game_y", gameY, "collapsed", Collapsed, "page", Page)); }
        public void ApplyLayout(Dictionary<string, object> d) { changingLayout = true; bool collapse = Data.Flag(d, "collapsed"); gameX = (int)Data.Number(d, "game_x"); gameY = (int)Data.Number(d, "game_y"); Size = new Size(Pixels((int)Data.Number(d, "width")), Pixels((int)Data.Number(d, "height"))); if (d.ContainsKey("x") && d["x"] != null) Location = new Point(Pixels((int)Data.Number(d, "x")), Pixels((int)Data.Number(d, "y"))); ClampBounds(); expandedBounds = Bounds; ShowPage(Data.Text(d, "page", "overview")); changingLayout = false; if (collapse) Collapse(); }
        void ResetLayout() { bool collapsed = Collapsed; Expand(); changingLayout = true; Size = new Size(Pixels(480), Pixels(600)); Rectangle area = Screen.FromControl(this).WorkingArea; gameX = 16; gameY = 16; Location = attached ? new Point(gameBounds.Left+Pixels(gameX), gameBounds.Top+Pixels(gameY)) : new Point(area.Right-Width-Pixels(16), area.Top+Pixels(40)); ClampBounds(); expandedBounds = Bounds; changingLayout = false; if (collapsed) Collapse(); SaveLayout(true); }
        public void FollowGame(Dictionary<string, object> d) { bool visible = Data.Flag(d, "visible"); object[] rect = Data.Array(d, "rect"); if (rect.Length == 4) { bool first = !attached; gameBounds = Rectangle.FromLTRB(Convert.ToInt32(rect[0]), Convert.ToInt32(rect[1]), Convert.ToInt32(rect[2]), Convert.ToInt32(rect[3])); attached = true; changingLayout = true; Location = new Point(gameBounds.Left+Pixels(gameX), gameBounds.Top+Pixels(gameY)); expandedBounds.Location = Location; ClampBounds(); changingLayout = false; TopMost = true; if (first && !LayoutRestored) Collapse(); }
            if (rect.Length == 0) { attached = false; TopMost = top.Checked; } if (attached) { if (visible && !Visible) Show(); else if (!visible && Visible) Hide(); Host.Visibility(this); Host.Visibility(Host.Lookup); } }
        void Reference() { int index = references.SelectedIndex; if (index >= 0 && index < referenceTokens.Count) Host.Send("reference", "index", index, "token", referenceTokens[index]); }
        void AdjustFloorReference() {
            for (TreeNode node = floor.SelectedNode; node != null; node = node.Parent) {
                string id = node.Name.Substring(node.Name.LastIndexOf('/') + 1);
                if (node.Name.StartsWith("/monsters/") && (id.StartsWith("actors.mobs.") || id.StartsWith("levels.") || id.StartsWith("items.quest."))) {
                    Host.Send("floor_reference", "id", id, "token", floorToken); return;
                }
                if (node.Name.StartsWith("/hidden/") && id.StartsWith("item-floor-")) {
                    Host.Send("floor_item_reference", "id", id, "token", floorToken); return;
                }
            }
            UI.ReplaceText(floorDetail, "请先选择本层可能出现的怪物，或主动揭示后选择具体物品，再查看数值。");
        }
        void RememberFloor(TreeNodeCollection nodes, HashSet<string> expanded, HashSet<string> known) { foreach (TreeNode node in nodes) { if (node.Nodes.Count > 0) known.Add(node.Name); if (node.IsExpanded) expanded.Add(node.Name); RememberFloor(node.Nodes, expanded, known); } }
        string FloorDetailText(TreeNode selected) {
            var details = new List<string>();
            for (TreeNode node = selected; node != null; node = node.Parent) {
                string detail = Convert.ToString(node.Tag);
                if (node == selected && String.IsNullOrEmpty(detail)) detail = node.Text;
                if (!String.IsNullOrEmpty(detail) && !details.Contains(detail)) details.Add(detail);
            }
            return String.Join("\n\n", details.ToArray());
        }
        void AddFloor(TreeNodeCollection nodes, object[] rows, string parent, HashSet<string> expanded, HashSet<string> known, string selected, ref TreeNode chosen) {
            foreach (object raw in rows) {
                var row = raw as Dictionary<string, object>; if (row == null) continue;
                string name = parent + "/" + Data.Text(row, "id", ""); var node = new TreeNode(Data.Text(row, "text", "")) { Name = name, Tag = Data.Text(row, "detail", "") };
                node.ToolTipText = Data.Text(row, "detail", node.Text); nodes.Add(node); AddFloor(node.Nodes, Data.Array(row, "children"), name, expanded, known, selected, ref chosen);
                if (expanded.Contains(name) || !known.Contains(name) && Data.Flag(row, "expanded")) node.Expand(); if (name == selected) chosen = node;
            }
        }
        void RenderFloor(Dictionary<string, object> d) {
            floorToken = Data.Text(d, "token", ""); floorCaption.Text = Data.Text(d, "caption", "当前楼层"); revealFloor.Enabled = Data.Flag(d, "enabled");
            revealFloor.Text = Data.Flag(d, "revealed") ? "收起本层隐藏内容" : "揭示本层隐藏内容";
            string owner = Data.Text(d, "owner", ""); bool same = owner == floorOwner; floorOwner = owner;
            object[] rows = Data.Array(d, "nodes"); string signature = owner + new JavaScriptSerializer { MaxJsonLength = 524288 }.Serialize(rows); if (signature == floorSignature) return;
            var expanded = new HashSet<string>(); var known = new HashSet<string>(); if (same) RememberFloor(floor.Nodes, expanded, known); string selected = !same || floor.SelectedNode == null ? "" : floor.SelectedNode.Name;
            TreeNode chosen = null; floor.BeginUpdate(); try { floor.Nodes.Clear(); AddFloor(floor.Nodes, rows, "", expanded, known, selected, ref chosen); floor.SelectedNode = chosen; if (chosen == null) UI.ReplaceText(floorDetail, "展开怪物后查看战斗数值、掉落物与概率；选择条目可读完整条件。隐藏资料需主动揭示。"); } finally { floor.EndUpdate(); }
            floorSignature = signature;
        }
        public void Render(Dictionary<string, object> d) {
            rendering = true; try { foreach (Control control in connectionControls) control.Enabled = !Data.Flag(d, "io_busy"); RenderFloor(Data.Object(d, "floor_guide")); UI.Article(summary, Data.Text(d, "text", "")); life.Text = Data.Text(d, "life", "等待有效存档"); statistics.Text = Data.Text(d, "statistics", ""); source.Text = Data.Text(d, "source", "等待游戏保存"); UI.ReplaceText(Status, Data.Text(d, "error", "")); Status.Visible = Status.Text.Length > 0; workspace.RowStyles[4] = new RowStyle(SizeType.Absolute, Status.Visible ? Font.Height*2+14 : 0); slot.SelectedIndex = (int)Math.Max(0, Math.Min(6, Data.Number(d, "slot"))); top.Checked = Data.Flag(d, "topmost"); if (!attached && TopMost != top.Checked) TopMost = top.Checked;
                var items = new List<string>(); foreach (object raw in Data.Array(d, "references")) items.Add(Convert.ToString(raw)); var old = new List<string>(); foreach (object raw in references.Items) old.Add(Convert.ToString(raw));
                var tokens = new List<string>(); foreach (object raw in Data.Array(d, "reference_tokens")) tokens.Add(Convert.ToString(raw));
                if (String.Join("\n", items.ToArray()) != String.Join("\n", old.ToArray()) || String.Join("|", tokens.ToArray()) != String.Join("|", referenceTokens.ToArray())) { int selected = references.SelectedIndex; string previous = selected >= 0 && selected < referenceTokens.Count ? referenceTokens[selected] : ""; references.BeginUpdate(); references.Items.Clear(); references.Items.AddRange(items.ToArray()); referenceTokens.Clear(); referenceTokens.AddRange(tokens); references.SelectedIndex = previous == "" ? -1 : referenceTokens.IndexOf(previous); references.EndUpdate(); } references.ItemHeight = Font.Height+12; overview.RowStyles[4] = new RowStyle(SizeType.Absolute, Math.Min(120, Math.Max(38, references.Items.Count*(Font.Height+12)+8)));
            } finally { rendering = false; }
        }
    }

    sealed class SettingsForm : BaseForm {
        readonly Dictionary<string, Control> values = new Dictionary<string, Control>();
        readonly Dictionary<string, TextBox> bindings = new Dictionary<string, TextBox>();
        readonly List<Control> persistenceControls = new List<Control>();
        readonly RichTextBox status = UI.Read("游玩设置保存与注册状态");
        readonly TableLayoutPanel outer = UI.Table(1);
        string shownStatus = "";
        bool rendering, changed, initialized;
        long draftRevision;
        public bool Dirty;
        public SettingsForm(Helper host) : base(host, "settings", "灯火 · 游玩显示与快捷键", 570, 700) {
            outer.Dock = DockStyle.Fill; Editable = outer; outer.RowCount = 3;
            outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, 0)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); status.Visible = false;
            var scroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill }; var table = UI.Table(2); table.Dock = DockStyle.Top; scroll.Controls.Add(table); int row = 0;
            foreach (string[] pair in new[] { new[] { "enabled", "启用游玩显示（只跟随游戏前台）" }, new[] { "alerts", "新存档新风险短暂提示" } }) { var check = UI.Name(new CheckBox { Text = pair[1], AutoSize = true, Dock = DockStyle.Fill }, pair[1]); values[pair[0]] = check; table.Controls.Add(check, 0, row); table.SetColumnSpan(check, 2); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); ++row; check.CheckedChanged += delegate { Edited(); }; }
            var anchor = UI.Combo("显示角落", new[] { "左上", "右上", "左下", "右下" }); values["anchor"] = anchor; table.Controls.Add(UI.Label("显示角落"), 0, row); table.Controls.Add(anchor, 1, row++); anchor.SelectedIndexChanged += delegate { Edited(); };
            foreach (string[] pair in new[] { new[] { "offset_x", "横向边距" }, new[] { "offset_y", "纵向边距" }, new[] { "font_scale", "字号倍率（1–2）" }, new[] { "opacity", "背景不透明度（0.5–1）" }, new[] { "notice_seconds", "短提醒时长（3–30秒）" } }) { var edit = UI.Edit(pair[1]); edit.MaxLength = 80; values[pair[0]] = edit; table.Controls.Add(UI.Label(pair[1]), 0, row); table.Controls.Add(edit, 1, row++); edit.TextChanged += delegate { Edited(); }; edit.Enter += delegate { scroll.ScrollControlIntoView(edit); }; }
            var notice = UI.Label("全局快捷键可修改或清空禁用；需含Ctrl或Alt。显示为存档参考，不读取实时画面。"); table.Controls.Add(notice, 0, row++); table.SetColumnSpan(notice, 2);
            foreach (string[] pair in new[] { new[] { "capture", "立即备份已落盘进度" }, new[] { "show", "显示管理窗口" }, new[] { "library", "数值手册" }, new[] { "backups", "存档历史" }, new[] { "play_toggle", "开关游玩显示" }, new[] { "quick", "游戏内只读速查" } }) { var edit = UI.Edit(pair[1] + "快捷键"); edit.MaxLength = 80; bindings[pair[0]] = edit; table.Controls.Add(UI.Label(pair[1]), 0, row); table.Controls.Add(edit, 1, row++); edit.TextChanged += delegate { Edited(); }; edit.Enter += delegate { scroll.ScrollControlIntoView(edit); }; }
            table.RowCount = row; for (int i = table.RowStyles.Count; i < row; ++i) table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var save = UI.Button("保存(&S)", delegate { FlushEdit(); Host.Send("settings_save", "surface", "settings"); });
            var reload = UI.Button("重新读取保存值", delegate { FlushEdit(); Host.Send("settings_reload", "surface", "settings"); });
            var unlock = UI.Button("拖动位置", delegate { FlushEdit(); Host.Send("unlock", "surface", "settings"); });
            persistenceControls.AddRange(new Control[] { save, reload, unlock });
            var registration = UI.Button("保存与快捷键状态", delegate { status.Visible = !status.Visible; outer.RowStyles[1] = new RowStyle(SizeType.Absolute, status.Visible ? Font.Height*6+16 : 0); });
            outer.Controls.Add(scroll, 0, 0); outer.Controls.Add(status, 0, 1); outer.Controls.Add(UI.Buttons(save, reload, registration, unlock, UI.Button("完整设置面板", delegate { Host.Send("panel", "page", "play-settings"); })), 0, 2); Controls.Add(outer);
        }
        void Edited() { if (rendering || !initialized || Host.Frozen) return; ++draftRevision; changed = Dirty = true; FlushEdit(); }
        public Dictionary<string, object> Raw() { var v = new Dictionary<string, object>(); var b = new Dictionary<string, object>(); foreach (var pair in values) { var check = pair.Value as CheckBox; v[pair.Key] = check == null ? (object)pair.Value.Text : check.Checked; } foreach (var pair in bindings) b[pair.Key] = pair.Value.Text; return Data.Map("values", v, "bindings", b, "draft_revision", draftRevision); }
        public void FlushEdit() { if (!initialized || !changed) return; changed = false; var raw = Raw(); Host.Send("settings_edit", "surface", "settings", "values", raw["values"], "bindings", raw["bindings"], "draft_revision", draftRevision); }
        public void Render(Dictionary<string, object> d) { foreach (Control control in persistenceControls) control.Enabled = !Data.Flag(d, "io_busy"); if (Data.Number(d, "draft_revision") < draftRevision) return; rendering = true; try { draftRevision = Data.Number(d, "draft_revision"); var v = Data.Object(d, "values"); var b = Data.Object(d, "bindings"); foreach (var pair in values) { var check = pair.Value as CheckBox; if (check != null) check.Checked = Data.Flag(v, pair.Key); else if (pair.Value.Text != Data.Text(v, pair.Key, "")) pair.Value.Text = Data.Text(v, pair.Key, ""); } foreach (var pair in bindings) if (pair.Value.Text != Data.Text(b, pair.Key, "")) pair.Value.Text = Data.Text(b, pair.Key, ""); string notice = Data.Text(d, "status", ""); if (notice.Length > 0 && notice != shownStatus) { status.Visible = true; outer.RowStyles[1] = new RowStyle(SizeType.Absolute, Font.Height*4+16); } shownStatus = notice; UI.ReplaceText(status, notice + "\n\n" + Data.Text(d, "registration", "")); Dirty = Data.Flag(d, "dirty"); initialized = true; } finally { rendering = false; } }
    }

    sealed class RecoveryForm : Form {
        public string Decision = "cancel";
        readonly Dictionary<string, ComboBox> selections = new Dictionary<string, ComboBox>();
        public Dictionary<string, object> Choices { get { var result = new Dictionary<string, object>(); foreach (var pair in selections) result[pair.Key] = pair.Value.SelectedIndex == 1 ? "draft" : pair.Value.SelectedIndex == 2 ? "original" : "current"; return result; } }
        static string Display(Dictionary<string, object> row, string key) { object value; return row.TryGetValue(key, out value) && value is bool ? ((bool)value ? "启用" : "关闭") : Data.Text(row, key, ""); }
        public RecoveryForm(Dictionary<string, object> data) {
            Text = "灯火 · 核对找回的设置"; AccessibleName = Text; TopMost = true;
            Font = new Font("Microsoft YaHei UI", 10F); AutoScaleMode = AutoScaleMode.Font; AutoScaleDimensions = new SizeF(7F, 17F);
            float scale; using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96F;
            Size = new Size((int)(780*scale), (int)(570*scale)); MinimumSize = new Size((int)(420*scale), (int)(300*scale));
            StartPosition = FormStartPosition.CenterParent; MinimizeBox = MaximizeBox = false;
            var outer = UI.Table(1); outer.Dock = DockStyle.Fill; outer.RowCount = 3;
            outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var notice = UI.Label(Data.Text(data, "text", "载入后仍需另行保存。")); notice.MaximumSize = new Size((int)(720*scale), 0); outer.Controls.Add(notice, 0, 0);
            var scroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill }; var table = UI.Table(1); table.Dock = DockStyle.Top; int index = 0;
            foreach (object item in Data.Array(data, "rows")) {
                var row = (Dictionary<string, object>)item; string key = Data.Text(row, "key", ""); string label = Data.Text(row, "label", key);
                var description = UI.Label(label + (Data.Flag(row, "conflict") ? " · 需要核对" : "") + "\n原保存值：" + Display(row, "original") + "\n当前保存值：" + Display(row, "current") + "\n找回的原始输入：" + Display(row, "draft")); description.MaximumSize = new Size((int)(690*scale), 0);
                table.Controls.Add(description, 0, index++);
                var choices = UI.Combo(label + "载入选择", Data.Flag(row, "original_available") ? new[] { "保留当前值", "找回草稿值", "恢复原保存值" } : new[] { "保留当前值", "找回草稿值" });
                choices.SelectedIndex = Data.Flag(row, "conflict") ? 0 : 1; selections[key] = choices; table.Controls.Add(choices, 0, index++);
            }
            table.RowCount = index; for (int i = 0; i < index; ++i) table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); scroll.Controls.Add(table); outer.Controls.Add(scroll, 0, 1);
            var cancel = UI.Button("取消载入", delegate { DialogResult = DialogResult.Cancel; }); CancelButton = cancel;
            outer.Controls.Add(UI.Buttons(UI.Button("按以上选择载入（尚未保存）", delegate { Decision = "restore"; DialogResult = DialogResult.OK; }), cancel), 0, 2); Controls.Add(outer);
            Shown += delegate { Rectangle area = Screen.FromControl(this).WorkingArea; Size = new Size(Math.Min(Width, area.Width-20), Math.Min(Height, area.Height-20)); };
        }
    }

    sealed class DecisionForm : Form {
        public string Decision = "cancel";
        public DecisionForm(string title, string message) { Text = title; AccessibleName = title; TopMost = true; Font = new Font("Microsoft YaHei UI", 10F); AutoScaleMode = AutoScaleMode.Font; AutoScaleDimensions = new SizeF(7F, 17F); float scale; using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96F; Size = new Size((int)(580*scale), (int)(240*scale)); MinimumSize = Size; StartPosition = FormStartPosition.CenterParent; MinimizeBox = MaximizeBox = false; FormBorderStyle = FormBorderStyle.FixedDialog;
            var table = UI.Table(1); table.Dock = DockStyle.Fill; table.RowCount = 2; table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); var label = UI.Label(message); label.MaximumSize = new Size((int)(550*scale), 0); table.Controls.Add(label, 0, 0);
            var save = UI.Button("保存草稿副本后继续(&S)", delegate { Decision = "saved"; DialogResult = DialogResult.OK; }); var cancel = UI.Button("取消(&C)", delegate { Decision = "cancel"; DialogResult = DialogResult.Cancel; }); var discard = UI.Button("明确放弃草稿(&D)", delegate { Decision = "discard"; DialogResult = DialogResult.No; });
            table.Controls.Add(UI.Buttons(save, cancel, discard), 0, 1); Controls.Add(table); CancelButton = cancel; AcceptButton = cancel;
        }
    }

    sealed class ExitWaitForm : Form {
        readonly Label message;
        readonly Button cancel;
        readonly Action requestCancel;
        bool canCancel, silent, cancelling;
        public ExitWaitForm(string text, bool allowCancel, Action callback) {
            requestCancel = callback;
            Text = AccessibleName = "灯火 · 正在结束本次辅助";
            TopMost = true; Font = new Font("Microsoft YaHei UI", 10F);
            AutoScaleMode = AutoScaleMode.Font; AutoScaleDimensions = new SizeF(7F, 17F);
            float scale; using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96F;
            Size = new Size((int)(580*scale), (int)(210*scale)); MinimumSize = Size;
            StartPosition = FormStartPosition.CenterParent; MinimizeBox = MaximizeBox = false;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            var table = UI.Table(1); table.Dock = DockStyle.Fill; table.RowCount = 2;
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            message = UI.Label(text); message.MaximumSize = new Size((int)(550*scale), 0); table.Controls.Add(message, 0, 0);
            cancel = UI.Button("取消退出，返回编辑(&C)", delegate { CancelWaiting(); });
            table.Controls.Add(UI.Buttons(cancel), 0, 1); Controls.Add(table);
            CancelButton = cancel; AcceptButton = cancel;
            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if (!silent) { e.Cancel = true; CancelWaiting(); }
            };
            SetProgress(text, allowCancel);
        }
        void CancelWaiting() {
            if (!canCancel || cancelling) return;
            cancelling = true; cancel.Enabled = false;
            message.Text = "正在取消退出；原始输入仍保留。";
            requestCancel();
        }
        public void SetProgress(string text, bool allowCancel) {
            canCancel = allowCancel; ControlBox = allowCancel;
            if (!cancelling || !allowCancel) message.Text = text;
            cancel.Enabled = allowCancel && !cancelling;
        }
        public void CloseSilently() { silent = true; Close(); }
    }

    sealed class NameForm : Form {
        readonly TextBox name = UI.Edit("方案名称"); readonly TextBox note = UI.Edit("用户用途/假设备注（未验证）"); readonly CheckBox update;
        public string PlanName { get { return name.Text; } } public string Note { get { return UI.Note(note.Text); } } public bool UpdateOriginal { get { return update.Checked; } }
        public Action Changed;
        public Control Editable;
        string baselineName, baselineNote; bool baselineUpdate, recovered;
        public bool Dirty { get { return recovered || PlanName != baselineName || Note != baselineNote || UpdateOriginal != baselineUpdate; } }
        public Dictionary<string, object> Raw() { return Data.Map("name", PlanName, "note", Note, "update", UpdateOriginal); }
        public NameForm(string initial, string notes, bool existing, Dictionary<string, object> pending) { Text = "灯火 · 保存参考方案"; AccessibleName = Text; TopMost = true; Font = new Font("Microsoft YaHei UI", 10F); AutoScaleMode = AutoScaleMode.Font; AutoScaleDimensions = new SizeF(7F, 17F); float scale; using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96F; Size = new Size((int)(560*scale), (int)(340*scale)); MinimumSize = new Size((int)(420*scale), (int)(280*scale)); StartPosition = FormStartPosition.CenterParent; MinimizeBox = MaximizeBox = false;
            var table = UI.Table(1); table.Dock = DockStyle.Fill; table.RowCount = 6; for (int i = 0; i < 6; ++i) table.RowStyles.Add(new RowStyle(i == 3 ? SizeType.Percent : SizeType.AutoSize, i == 3 ? 100 : 0));
            name.Text = existing ? initial + " 副本" : initial; name.MaxLength = 80; note.MaxLength = 1200; note.Multiline = true; note.AcceptsReturn = true; note.ScrollBars = ScrollBars.Vertical; note.Text = UI.Multiline(notes);
            update = UI.Name(new CheckBox { Text = "更新原方案（保留名称与身份）", AutoSize = true, Enabled = existing }, "更新原方案（保留名称与身份）"); update.CheckedChanged += delegate { name.ReadOnly = update.Checked; name.Text = update.Checked ? initial : initial + " 副本"; };
            table.Controls.Add(UI.Label("方案名称"), 0, 0); table.Controls.Add(name, 0, 1); table.Controls.Add(UI.Label("用户用途/假设备注（可选，未验证）"), 0, 2); table.Controls.Add(note, 0, 3); table.Controls.Add(update, 0, 4);
            var save = UI.Button("保存(&S)", delegate { if (name.Text.Trim().Length == 0) { MessageBox.Show(this, "请填写方案名称。", Text); name.Focus(); } else DialogResult = DialogResult.OK; }); var cancel = UI.Button("取消", delegate { DialogResult = DialogResult.Cancel; }); table.Controls.Add(UI.Buttons(save, cancel), 0, 5); Controls.Add(table); Editable = table; AcceptButton = save; CancelButton = cancel;
            baselineName = PlanName; baselineNote = Note; baselineUpdate = UpdateOriginal;
            recovered = pending.Count > 0;
            if (recovered) { update.Checked = existing && Data.Flag(pending, "update"); name.Text = Data.Text(pending, "name", name.Text); note.Text = UI.Multiline(Data.Text(pending, "note", note.Text)); }
            foreach (Control control in new Control[] { name, note, update }) { control.TextChanged += delegate { if (Changed != null) Changed(); }; }
            update.CheckedChanged += delegate { if (Changed != null) Changed(); };
        }
    }

    static class Program {
        [STAThread] static void Main(string[] args) {
            if (args.Length == 3 && args[0] == "--choose-directory" && (args[1] == "save" || args[1] == "backup") && args[2].Length <= 1000) {
                // Parent owns this dialog. EOF closes it without changing any settings.
                new Thread(new ThreadStart(delegate { try { Console.OpenStandardInput().ReadByte(); } catch { } Environment.Exit(0); })) { IsBackground = true }.Start();
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                object result;
                try {
                    using (var picker = new FolderBrowserDialog { Description = args[1] == "save" ? "选择包含 game1、game2 等文件夹的存档目录；选定后仍需保存设置" : "选择已有本地备份文件夹；选定后仍需预览并确认", ShowNewFolderButton = false }) {
                        if (Directory.Exists(args[2])) picker.SelectedPath = args[2];
                        bool accepted = picker.ShowDialog() == DialogResult.OK;
                        result = Data.Map("cancelled", !accepted, "path", accepted ? picker.SelectedPath : "");
                    }
                } catch (Exception error) { result = Data.Map("error", error.Message); }
                using (var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false))) { output.WriteLine(new JavaScriptSerializer().Serialize(result)); }
                return;
            }
            if (args.Length != 1 || args[0].Length != 32) return;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Helper(args[0]));
        }
    }
}
