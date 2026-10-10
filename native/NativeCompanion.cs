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
        DecisionForm activeExit;
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
                        case "lookup_state": Lookup.Render(d); break;
                        case "settings_state": Settings.Render(d); break;
                        case "plans": Plans.Render(d); if (!Plans.Visible) ShowSurface("plans"); break;
                        case "focus_search": ShowSurface("lookup"); Lookup.FocusSearch(); break;
                        case "name_plan": NamePlan(d); break;
                        case "confirm": Confirm(d); break;
                        case "exit_request": ExitRequest(Data.Object(d, "state")); break;
                        case "exit_save_error": ExitRequest(Data.Object(d, "state"), Data.Text(d, "message", "草稿副本未能保存"), true); break;
                        case "exit_cancelled": CancelExit(Data.Text(d, "request_id", "")); break;
                        case "exit_finished": Manager.Status.Text = Data.Text(d, "message", "最后备份结果尚未确认，请在下次启动核对退出回执。"); break;
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
        public void Visibility(BaseForm form) { Send("visibility", "surface", form.Surface, "visible", form.Visible, "hwnd", form.Handle.ToInt64()); }
        public void ShowSurface(string surface) {
            BaseForm form = surface == "lookup" ? (BaseForm)Lookup : surface == "settings" ? (BaseForm)Settings : surface == "plans" ? (BaseForm)Plans : (BaseForm)Manager;
            if (!form.Visible) form.Show(); if (form.WindowState == FormWindowState.Minimized) form.WindowState = FormWindowState.Normal;
            form.Activate(); Visibility(form); if (surface == "lookup") Lookup.FocusSearch();
        }
        public void HideSurface(string surface) {
            BaseForm form = surface == "lookup" ? (BaseForm)Lookup : surface == "settings" ? (BaseForm)Settings : surface == "plans" ? (BaseForm)Plans : (BaseForm)Manager;
            form.Hide(); Visibility(form); if (surface == "plans" && Lookup.Visible) Lookup.Activate();
        }
        void SetFrozen(bool freeze) { Manager.Editable.Enabled = !freeze; Lookup.Editable.Enabled = !freeze; Settings.Editable.Enabled = !freeze; Plans.Enabled = !freeze; if (activeName != null) activeName.Editable.Enabled = !freeze; }
        void CloseExitDialog() { var dialog = activeExit; activeExit = null; if (dialog != null) dialog.Close(); }
        void CancelExit(string id) {
            if (!exitRequests.Cancel(id)) return;
            CloseExitDialog(); Frozen = false; SetFrozen(false);
        }
        void ExitRequest(Dictionary<string, object> state, string error = "", bool retry = false) {
            string id = Data.Text(state, "id", "");
            if (retry ? !exitRequests.IsCurrent(id) : !exitRequests.Begin(id)) return;
            CloseExitDialog();
            Lookup.FlushEdit(); Settings.FlushEdit();
            Frozen = true; SetFrozen(true);
            var lookup = Lookup.Raw(); var settings = Settings.Raw();
            bool dirty = Lookup.Dirty || Settings.Dirty || SaveDraft != null || error.Length > 0;
            string decision = "clean";
            if (dirty) {
                using (var dialog = new DecisionForm("退出灯火", (error.Length > 0 ? "保存副本未完成：" + error + "\n原始草稿仍保留。\n" : "") + "数值速查或游玩设置有未保存草稿。保存副本会保留全部草稿；取消可返回继续编辑。")) {
                    activeExit = dialog;
                    try {
                        dialog.ShowDialog(Manager.Visible ? (IWin32Window)Manager : Lookup.Visible ? (IWin32Window)Lookup : (IWin32Window)Settings);
                        decision = dialog.Decision;
                    } finally { if (activeExit == dialog) activeExit = null; }
                }
            }
            if (!exitRequests.IsCurrent(id)) return;
            Send("exit_decision", "request_id", id, "decision", decision, "lookup", Lookup.Dirty || SaveDraft != null ? (object)lookup : null, "settings", Settings.Dirty ? (object)settings : null);
            if (decision == "cancel") { CloseExitDialog(); Frozen = false; SetFrozen(false); }
        }
        void Confirm(Dictionary<string, object> d) {
            Lookup.FlushEdit(); Settings.FlushEdit();
            string surface = Data.Text(d, "surface", "lookup"), purpose = Data.Text(d, "purpose", "replace");
            using (var dialog = new DecisionForm(Data.Text(d, "title", "替换草稿"), Data.Text(d, "text", "请确认当前草稿"))) {
                dialog.ShowDialog(surface == "settings" ? (IWin32Window)Settings : Lookup);
                Send(purpose == "settings_reload" ? "settings_reload_decision" : "replace_decision", "surface", surface, "decision", dialog.Decision);
            }
        }
        void NamePlan(Dictionary<string, object> d) {
            using (var dialog = new NameForm(Data.Text(d, "name", "参考方案"), Data.Text(d, "note", ""), Data.Flag(d, "existing"), Data.Object(d, "pending_save"))) {
                activeName = dialog;
                dialog.Changed = delegate { if (!Frozen) Send("save_dialog_edit", "surface", "lookup", "pending_save", dialog.Dirty ? (object)dialog.Raw() : null); };
                try { if (dialog.ShowDialog(Lookup) == DialogResult.OK && !Frozen)
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
                    var row = (Dictionary<string, object>)item; string kind = Data.Text(row, "draft_kind", ""); string surface = kind == "numeric" ? "数值速查" : kind == "play-settings" ? "游玩设置" : kind == "offline-native" ? "离线原生副本" : "完整面板";
                    double savedAt; string when = Double.TryParse(Data.Text(row, "saved", ""), out savedAt) && savedAt >= 0 && savedAt <= 32503680000 ? new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(savedAt).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss") : "保存时间不可用";
                    draftRows[Data.Text(row, "id", "")] = row;
                    string text = (Data.Text(row, "state", "active") == "archived" ? "[已归档] " : "[未完成] ") + Data.Text(row, "label", "无法读取的草稿") + " · " + surface + " · " + when + " · " + Data.Text(row, "id", "").Substring(0, 12); string error = Data.Text(row, "error", "");
                    object[] components = Data.Array(row, "components");
                    if (kind == "offline-native" && components.Length > 0 && error.Length == 0) {
                        foreach (object part in components) { string component = Convert.ToString(part); list.Items.Add(new Choice(Data.Text(row, "id", ""), text + " · 载入" + (component == "numeric" ? "数值表单" : "游玩设置表单"), component)); }
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
                dialog.ShowDialog(Settings);
                Send("settings_recovery_decision", "surface", "settings", "decision", dialog.Decision,
                    "choices", dialog.Choices);
            }
        }
        void Shutdown() { stopping = true; timer.Stop(); foreach (BaseForm f in new BaseForm[] { Manager, Lookup, Settings, Plans }) f.CloseForShutdown(); outgoing.CompleteAdding(); ExitThread(); }
    }

    static class UI {
        public static T Name<T>(T control, string name) where T : Control { control.AccessibleName = name; control.Name = name; control.Margin = new Padding(5); return control; }
        public static Label Label(string text) { return Name(new Label { Text = text, AutoSize = true, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, TabStop = false }, text); }
        public static TextBox Edit(string name) { return Name(new TextBox { Dock = DockStyle.Fill }, name); }
        public static RichTextBox Read(string name) { return Name(new RichTextBox { ReadOnly = true, Enabled = true, TabStop = true, Dock = DockStyle.Fill, WordWrap = true, DetectUrls = false, BorderStyle = BorderStyle.FixedSingle }, name); }
        public static ListBox List(string name) { return Name(new ListBox { IntegralHeight = false, HorizontalScrollbar = true, Dock = DockStyle.Fill }, name); }
        public static Button Button(string label, EventHandler clicked) { var b = Name(new Button { Text = label, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(0, 30), Dock = DockStyle.Fill }, label.Replace("&", "")); b.Click += clicked; return b; }
        public static TableLayoutPanel Table(int cols) { var table = new TableLayoutPanel { ColumnCount = cols, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(7) }; for (int i = 0; i < cols; ++i) table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / cols)); return table; }
        public static ComboBox Combo(string name, string[] choices) { var c = Name(new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill }, name); c.Items.AddRange(choices); if (choices.Length > 0) c.SelectedIndex = 0; return c; }
        public static FlowLayoutPanel Buttons(params Control[] controls) { var panel = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true }; foreach (var control in controls) { control.Dock = DockStyle.None; panel.Controls.Add(control); } return panel; }
        public static void ReplaceText(RichTextBox field, string text) { if (field.Text == text) return; int start = field.SelectionStart, length = field.SelectionLength; field.Text = text; field.Select(Math.Min(start, field.TextLength), Math.Min(length, Math.Max(0, field.TextLength-start))); }
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
            Font = new Font("Microsoft YaHei UI", 10F); AutoScaleMode = AutoScaleMode.Font;
            AutoScaleDimensions = new SizeF(7F, 17F);
            using (Graphics graphics = CreateGraphics()) SystemDpi = graphics.DpiX;
            float dpiScale = SystemDpi / 96F;
            Size = new Size((int)(width * dpiScale), (int)(height * dpiScale)); MinimumSize = new Size((int)(380 * dpiScale), (int)(300 * dpiScale));
            if (surface == "lookup" || surface == "settings" || surface == "plans") TopMost = true;
            StartPosition = FormStartPosition.CenterScreen; ShowInTaskbar = true; KeyPreview = true;
            Shown += delegate { Rectangle area = Screen.FromControl(this).WorkingArea; Size = new Size(Math.Min(Width, area.Width-20), Math.Min(Height, area.Height-20)); Host.Visibility(this); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (!shutdown && Surface != "drafts") { e.Cancel = true; if (Surface == "lookup") Host.Send("hide", "surface", "lookup"); else Host.HideSurface(Surface); } };
            KeyDown += delegate(object sender, KeyEventArgs e) {
                if (e.KeyCode == Keys.Escape && !Host.Frozen) { if (Surface == "drafts") CloseForShutdown(); else if (Surface == "lookup") Host.Send("hide", "surface", "lookup"); else Host.HideSurface(Surface); e.Handled = true; }
                else if (e.KeyCode == Keys.F1) { Host.Send("panel", "page", "help"); e.Handled = true; }
            };
        }
        public void CloseForShutdown() { shutdown = true; Close(); }
    }

    sealed class LookupForm : BaseForm {
        readonly TextBox search = UI.Edit("搜索物品、敌人或技能");
        readonly ListBox rows = UI.List("搜索结果列表");
        readonly TableLayoutPanel parameters = UI.Table(2);
        readonly Panel parameterScroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill };
        readonly RichTextBox result = UI.Read("数值结果与适用条件");
        readonly RichTextBox status = UI.Read("数值参数与保存状态");
        readonly TextBox note = UI.Edit("用户用途/假设备注（未验证）");
        readonly Dictionary<string, TextBox> edits = new Dictionary<string, TextBox>();
        readonly Dictionary<string, Label> labels = new Dictionary<string, Label>();
        readonly ToolStripMenuItem sources = new ToolStripMenuItem("官方依据");
        readonly ToolStripMenuItem undo = new ToolStripMenuItem("撤回本次参数导入");
        readonly Button more;
        bool rendering, changed;
        long draftRevision;
        public bool Dirty;
        string fieldsSignature = "";
        public LookupForm(Helper host) : base(host, "lookup", "灯火 · 数值速查", 560, 740) {
            var outer = UI.Table(1); outer.Dock = DockStyle.Fill; Editable = outer;
            var menu = new MenuStrip { Dock = DockStyle.Top }; var actions = new ToolStripMenuItem("资料操作(&O)");
            foreach (string[] pair in new string[][] { new[] { "收藏 / 取消收藏", "favorite" }, new[] { "保存 / 更新 / 另存方案", "save_plan" }, new[] { "打开已保存方案", "choose_plan" }, new[] { "重新读取当前方案", "reload_plan" }, new[] { "固定到游戏速查", "pin" }, new[] { "清除固定", "clear_pin" }, new[] { "来源与适用限制", "provenance" } }) {
                string action = pair[1]; var item = new ToolStripMenuItem(pair[0]); item.AccessibleName = pair[0]; item.Click += delegate { FlushEdit(); Host.Send(action, "surface", "lookup"); }; actions.DropDownItems.Add(item);
            }
            undo.Click += delegate { Host.Send("undo_import", "surface", "lookup"); }; actions.DropDownItems.Add(undo); actions.DropDownItems.Add(sources);
            var panel = new ToolStripMenuItem("完整资料库"); panel.Click += delegate { Host.Send("panel", "page", "workspace"); }; actions.DropDownItems.Add(panel);
            foreach (string[] pair in new string[][] { new[] { "共享角色条件（网页）", "workspace" }, new[] { "装备比较（网页）", "inventory" }, new[] { "完整炼金规划（网页）", "alchemy" } }) {
                string page = pair[1]; var item = new ToolStripMenuItem(pair[0]); item.AccessibleName = pair[0]; item.Click += delegate { FlushEdit(); Host.Send("panel", "page", page); }; actions.DropDownItems.Add(item);
            }
            menu.Items.Add(actions); MainMenuStrip = menu;
            outer.RowCount = 10;
            for (int i = 0; i < 10; ++i) outer.RowStyles.Add(new RowStyle(i == 2 ? SizeType.Absolute : i == 4 ? SizeType.Percent : i == 8 ? SizeType.Percent : i == 9 ? SizeType.Absolute : SizeType.AutoSize, i == 2 ? 90 : i == 4 ? 35 : i == 8 ? 65 : i == 9 ? 62 : 0));
            outer.Controls.Add(UI.Label("搜索物品、敌人或技能"), 0, 0); outer.Controls.Add(search, 0, 1); outer.Controls.Add(rows, 0, 2);
            more = UI.Button("显示更多结果", delegate { Host.Send("more", "surface", "lookup"); }); outer.Controls.Add(more, 0, 3);
            parameters.Dock = DockStyle.Top; parameterScroll.Controls.Add(parameters); outer.Controls.Add(parameterScroll, 0, 4);
            outer.Controls.Add(UI.Button("按所填参数计算(&C)", delegate { FlushEdit(); Host.Send("calculate", "surface", "lookup"); }), 0, 5);
            outer.Controls.Add(UI.Label("用户用途/假设备注（未验证，可选）"), 0, 6); note.Multiline = true; note.AcceptsReturn = true; note.ScrollBars = ScrollBars.Vertical; note.MinimumSize = new Size(0, Font.Height*3+12); note.MaxLength = 1200; outer.Controls.Add(note, 0, 7);
            outer.Controls.Add(result, 0, 8); outer.Controls.Add(status, 0, 9);
            Controls.Add(outer); Controls.Add(menu);
            search.MaxLength = 200; search.TextChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("query", "surface", "lookup", "text", search.Text); };
            search.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { Host.Send("first", "surface", "lookup"); e.SuppressKeyPress = true; } else if (e.KeyCode == Keys.Down) { rows.Focus(); if (rows.Items.Count > 0 && rows.SelectedIndex < 0) rows.SelectedIndex = 0; e.SuppressKeyPress = true; } };
            rows.SelectedIndexChanged += delegate { if (!rendering && rows.SelectedIndex >= 0 && !Host.Frozen) Host.Send("select", "surface", "lookup", "index", rows.SelectedIndex); };
            rows.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter && rows.SelectedIndex >= 0) { Host.Send("select", "surface", "lookup", "index", rows.SelectedIndex); e.SuppressKeyPress = true; } };
            note.TextChanged += delegate { Edited(); };
            KeyDown += delegate(object sender, KeyEventArgs e) { if (e.Control && e.KeyCode == Keys.F) { FocusSearch(); e.SuppressKeyPress = true; } };
        }
        void Edited() { if (rendering || Host.Frozen) return; ++draftRevision; changed = Dirty = true; result.Text = "参数或备注已修改，请核对并重新计算。"; status.Text = "有未保存草稿。"; FlushEdit(); }
        public Dictionary<string, object> Raw() {
            var values = new Dictionary<string, object>(); foreach (var pair in edits) values[pair.Key] = pair.Value.Text;
            var raw = Data.Map("values", values, "note", UI.Note(note.Text), "draft_revision", draftRevision);
            Host.CaptureSaveDraft(raw); return raw;
        }
        public void FlushEdit() { if (!changed) return; changed = false; var raw = Raw(); Host.Send("edit", "surface", "lookup", "values", raw["values"], "note", raw["note"], "draft_revision", draftRevision); }
        public void FocusSearch() { search.Focus(); search.SelectAll(); }
        public void Render(Dictionary<string, object> d) {
            if (Data.Number(d, "draft_revision") < draftRevision) return;
            rendering = true;
            try {
                draftRevision = Data.Number(d, "draft_revision"); Dirty = Data.Flag(d, "dirty");
                if (!search.Focused) search.Text = Data.Text(d, "query", "");
                int selected = rows.SelectedIndex; string old = selected >= 0 ? Convert.ToString(rows.SelectedItem) : "";
                var texts = new List<string>(); foreach (object raw in Data.Array(d, "rows")) texts.Add(Data.Text((Dictionary<string, object>)raw, "text", ""));
                string newRows = String.Join("\n", texts.ToArray()); var oldRows = new List<string>(); foreach (object item in rows.Items) oldRows.Add(Convert.ToString(item));
                if (newRows != String.Join("\n", oldRows.ToArray())) { rows.BeginUpdate(); rows.Items.Clear(); rows.Items.AddRange(texts.ToArray()); rows.SelectedIndex = old == "" ? -1 : rows.Items.IndexOf(old); rows.EndUpdate(); }
                rows.ItemHeight = Font.Height + 7; more.Enabled = Data.Flag(d, "can_more"); undo.Enabled = Data.Flag(d, "undo");
                var fields = Data.Array(d, "fields"); var keys = new List<string>(); foreach (object raw in fields) keys.Add(Data.Text((Dictionary<string, object>)raw, "key", ""));
                string signature = String.Join("|", keys.ToArray());
                if (signature != fieldsSignature) {
                    parameters.SuspendLayout(); parameters.Controls.Clear(); parameters.RowStyles.Clear(); edits.Clear(); labels.Clear(); parameters.RowCount = fields.Length; fieldsSignature = signature;
                    for (int i = 0; i < fields.Length; ++i) { var field = (Dictionary<string, object>)fields[i]; string key = Data.Text(field, "key", ""); string label = Data.Text(field, "label", key); var text = UI.Edit(label); text.MaxLength = 80; text.AccessibleDescription = "来源与范围见相邻说明";
                        text.TextChanged += delegate { Edited(); }; text.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { FlushEdit(); Host.Send("calculate", "surface", "lookup"); e.SuppressKeyPress = true; } };
                        text.Enter += delegate { parameterScroll.ScrollControlIntoView(text); };
                        var heading = UI.Label(label); edits[key] = text; labels[key] = heading; parameters.RowStyles.Add(new RowStyle(SizeType.AutoSize)); parameters.Controls.Add(heading, 0, i); parameters.Controls.Add(text, 1, i);
                    }
                    parameters.ResumeLayout(true);
                }
                foreach (object raw in fields) { var field = (Dictionary<string, object>)raw; string key = Data.Text(field, "key", ""); string text = Data.Text(field, "raw", ""); if (edits[key].Text != text) edits[key].Text = text;
                    labels[key].Text = Data.Text(field, "label", key) + "\n" + Data.Text(field, "origin", "") + " · " + Data.Text(field, "min", "") + "–" + Data.Text(field, "max", ""); edits[key].AccessibleDescription = labels[key].Text;
                }
                string noteText = UI.Multiline(Data.Text(d, "note", "")); if (note.Text != noteText) note.Text = noteText;
                UI.ReplaceText(result, Data.Text(d, "result", "")); UI.ReplaceText(status, Data.Text(d, "status", ""));
                sources.DropDownItems.Clear(); int index = 0; foreach (object raw in Data.Array(d, "sources")) { var link = (Dictionary<string, object>)raw; int selectedLink = index++; var item = new ToolStripMenuItem(Data.Text(link, "label", "官方依据")); item.Click += delegate { Host.Send("source_link", "surface", "lookup", "index", selectedLink); }; sources.DropDownItems.Add(item); }
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
            table.Controls.Add(UI.Label("数值方案在此打开；角色条件、装备比较、手动局势及炼金方案将按所选身份交给完整网页面板。"), 0, 0); table.Controls.Add(search, 0, 1);
            var filters = UI.Table(4); filters.Dock = DockStyle.Fill; filters.Controls.Add(UI.Label("类型"), 0, 0); filters.Controls.Add(kind, 1, 0); filters.Controls.Add(UI.Label("排序"), 2, 0); filters.Controls.Add(order, 3, 0); table.Controls.Add(filters, 0, 2); table.Controls.Add(rows, 0, 3); table.Controls.Add(selected, 0, 4);
            open = UI.Button("打开所选方案(&O)", delegate { OpenSelected(); }); table.Controls.Add(open, 0, 5); Controls.Add(table);
            search.TextChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("filter_plans", "surface", "lookup", "query", search.Text, "kind", kind.Text, "order", order.Text); };
            foreach (ComboBox control in new ComboBox[] { kind, order }) { control.SelectedIndexChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("filter_plans", "surface", "lookup", "query", search.Text, "kind", kind.Text, "order", order.Text); }; }
            rows.SelectedIndexChanged += delegate { selected.Text = rows.SelectedItem == null ? "没有匹配方案" : rows.SelectedItem.ToString(); };
            rows.DoubleClick += delegate { OpenSelected(); }; rows.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { OpenSelected(); e.SuppressKeyPress = true; } };
            search.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Down) { rows.Focus(); e.SuppressKeyPress = true; } };
        }
        void OpenSelected() { var row = rows.SelectedItem as Choice; if (row != null) { Host.Send("open_plan", "surface", "lookup", "id", row.Id); Host.HideSurface("plans"); } }
        public void Render(Dictionary<string, object> d) { rendering = true; var old = rows.SelectedItem as Choice; string id = old == null ? "" : old.Id; rows.BeginUpdate(); rows.Items.Clear(); int select = 0; foreach (object raw in Data.Array(d, "rows")) { var row = (Dictionary<string, object>)raw; var choice = new Choice(Data.Text(row, "id", ""), Data.Text(row, "text", "")); if (choice.Id == id) select = rows.Items.Count; rows.Items.Add(choice); } rows.ItemHeight = Font.Height + 8; if (rows.Items.Count > 0) rows.SelectedIndex = select; else selected.Text = "没有匹配方案；可更改搜索或类型。"; open.Enabled = rows.Items.Count > 0; rows.EndUpdate(); rendering = false; }
    }

    sealed class ManagerForm : BaseForm {
        readonly RichTextBox summary = UI.Read("当前存档、生命、风险、资源与备份全文");
        public readonly RichTextBox Status = UI.Read("管理操作和快捷键实际状态");
        readonly ComboBox slot = UI.Combo("存档槽位", new[] { "自动跟随", "槽位 1", "槽位 2", "槽位 3", "槽位 4", "槽位 5", "槽位 6" });
        readonly CheckBox top = UI.Name(new CheckBox { Text = "管理窗口置顶", AutoSize = true }, "管理窗口置顶");
        readonly ListBox references = UI.List("风险与资源参考资料");
        readonly Panel options = new Panel { Dock = DockStyle.Fill, AutoSize = true, Visible = false };
        readonly Button compact;
        bool rendering, isCompact;
        public ManagerForm(Helper host) : base(host, "manager", "灯火 · 地牢助手", 550, 650) {
            var table = UI.Table(1); table.Dock = DockStyle.Fill; Editable = table; table.RowCount = 6;
            table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); table.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); table.RowStyles.Add(new RowStyle(SizeType.Absolute, 84)); table.RowStyles.Add(new RowStyle(SizeType.Absolute, 80)); table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            compact = UI.Button("收起", delegate { isCompact = !isCompact; references.Visible = !isCompact; summary.Visible = true; compact.Text = isCompact ? "展开" : "收起"; });
            table.Controls.Add(UI.Buttons(compact, UI.Button("设置", delegate { options.Visible = !options.Visible; }), UI.Button("退出", delegate { Host.Send("exit"); })), 0, 0);
            var settings = UI.Table(2); settings.Dock = DockStyle.Top; settings.Controls.Add(UI.Label("存档槽位"), 0, 0); settings.Controls.Add(slot, 1, 0); settings.Controls.Add(top, 0, 1);
            settings.Controls.Add(UI.Button("刷新", delegate { Host.Send("refresh"); }), 1, 1);
            settings.Controls.Add(UI.Button("选择存档目录…", delegate { using (var picker = new FolderBrowserDialog { Description = "选择包含 game1、game2 等文件夹的存档目录", ShowNewFolderButton = false }) { if (picker.ShowDialog(this) == DialogResult.OK) Host.Send("directory", "path", picker.SelectedPath); } }), 0, 2);
            settings.Controls.Add(UI.Button("游玩显示与快捷键", delegate { Host.Send("show_settings"); }), 1, 2); options.Controls.Add(settings); table.Controls.Add(options, 0, 1);
            table.Controls.Add(summary, 0, 2); table.Controls.Add(references, 0, 3); table.Controls.Add(Status, 0, 4);
            table.Controls.Add(UI.Buttons(UI.Button("查数值", delegate { Host.Send("show_lookup"); }), UI.Button("存档历史", delegate { Host.Send("panel", "page", "backups"); }), UI.Button("完整面板", delegate { Host.Send("panel", "page", "overview"); }), UI.Button("立即备份", delegate { Host.Send("capture"); }), UI.Button("载入未完成草稿", delegate { Host.Send("list_drafts"); })), 0, 5); Controls.Add(table);
            slot.SelectedIndexChanged += delegate { if (!rendering) Host.Send("slot", "index", slot.SelectedIndex); };
            top.CheckedChanged += delegate { if (!rendering) Host.Send("pin_manager", "checked", top.Checked); };
            references.DoubleClick += delegate { Reference(); }; references.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { Reference(); e.SuppressKeyPress = true; } };
        }
        void Reference() { if (references.SelectedIndex >= 0) Host.Send("reference", "index", references.SelectedIndex); }
        public void Render(Dictionary<string, object> d) {
            rendering = true; try { UI.ReplaceText(summary, Data.Text(d, "text", "")); UI.ReplaceText(Status, Data.Text(d, "error", "") + "\n" + Data.Text(d, "capabilities", "")); slot.SelectedIndex = (int)Math.Max(0, Math.Min(6, Data.Number(d, "slot"))); top.Checked = Data.Flag(d, "topmost"); if (TopMost != top.Checked) TopMost = top.Checked;
                var items = new List<string>(); foreach (object raw in Data.Array(d, "references")) items.Add(Convert.ToString(raw)); var old = new List<string>(); foreach (object raw in references.Items) old.Add(Convert.ToString(raw));
                if (String.Join("\n", items.ToArray()) != String.Join("\n", old.ToArray())) { string previous = references.SelectedItem == null ? "" : references.SelectedItem.ToString(); references.BeginUpdate(); references.Items.Clear(); references.Items.AddRange(items.ToArray()); references.SelectedIndex = references.Items.IndexOf(previous); references.EndUpdate(); }
            } finally { rendering = false; }
        }
    }

    sealed class SettingsForm : BaseForm {
        readonly Dictionary<string, Control> values = new Dictionary<string, Control>();
        readonly Dictionary<string, TextBox> bindings = new Dictionary<string, TextBox>();
        readonly RichTextBox status = UI.Read("游玩设置保存与注册状态");
        bool rendering, changed, initialized;
        long draftRevision;
        public bool Dirty;
        public SettingsForm(Helper host) : base(host, "settings", "灯火 · 游玩显示与快捷键", 570, 700) {
            var outer = UI.Table(1); outer.Dock = DockStyle.Fill; Editable = outer; outer.RowCount = 3;
            outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); outer.RowStyles.Add(new RowStyle(SizeType.Absolute, 155)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var scroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill }; var table = UI.Table(2); table.Dock = DockStyle.Top; scroll.Controls.Add(table); int row = 0;
            foreach (string[] pair in new[] { new[] { "enabled", "启用游玩显示（只跟随游戏前台）" }, new[] { "alerts", "新存档新风险短暂提示" } }) { var check = UI.Name(new CheckBox { Text = pair[1], AutoSize = true, Dock = DockStyle.Fill }, pair[1]); values[pair[0]] = check; table.Controls.Add(check, 0, row); table.SetColumnSpan(check, 2); table.RowStyles.Add(new RowStyle(SizeType.AutoSize)); ++row; check.CheckedChanged += delegate { Edited(); }; }
            var anchor = UI.Combo("显示角落", new[] { "左上", "右上", "左下", "右下" }); values["anchor"] = anchor; table.Controls.Add(UI.Label("显示角落"), 0, row); table.Controls.Add(anchor, 1, row++); anchor.SelectedIndexChanged += delegate { Edited(); };
            foreach (string[] pair in new[] { new[] { "offset_x", "横向边距" }, new[] { "offset_y", "纵向边距" }, new[] { "font_scale", "字号倍率（1–2）" }, new[] { "opacity", "背景不透明度（0.5–1）" }, new[] { "notice_seconds", "短提醒时长（3–30秒）" } }) { var edit = UI.Edit(pair[1]); edit.MaxLength = 80; values[pair[0]] = edit; table.Controls.Add(UI.Label(pair[1]), 0, row); table.Controls.Add(edit, 1, row++); edit.TextChanged += delegate { Edited(); }; edit.Enter += delegate { scroll.ScrollControlIntoView(edit); }; }
            var notice = UI.Label("全局快捷键可修改或清空禁用；需含Ctrl或Alt。显示为存档参考，不读取实时画面。"); table.Controls.Add(notice, 0, row++); table.SetColumnSpan(notice, 2);
            foreach (string[] pair in new[] { new[] { "capture", "立即备份已落盘进度" }, new[] { "show", "显示管理窗口" }, new[] { "library", "数值手册" }, new[] { "backups", "存档历史" }, new[] { "play_toggle", "开关游玩显示" }, new[] { "quick", "游戏内只读速查" } }) { var edit = UI.Edit(pair[1] + "快捷键"); edit.MaxLength = 80; bindings[pair[0]] = edit; table.Controls.Add(UI.Label(pair[1]), 0, row); table.Controls.Add(edit, 1, row++); edit.TextChanged += delegate { Edited(); }; edit.Enter += delegate { scroll.ScrollControlIntoView(edit); }; }
            table.RowCount = row; for (int i = table.RowStyles.Count; i < row; ++i) table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            outer.Controls.Add(scroll, 0, 0); outer.Controls.Add(status, 0, 1); outer.Controls.Add(UI.Buttons(UI.Button("保存(&S)", delegate { FlushEdit(); Host.Send("settings_save", "surface", "settings"); }), UI.Button("重新读取保存值", delegate { Host.Send("settings_reload", "surface", "settings"); }), UI.Button("拖动位置", delegate { FlushEdit(); Host.Send("unlock", "surface", "settings"); }), UI.Button("数值速查", delegate { Host.Send("show_lookup"); }), UI.Button("完整设置面板", delegate { Host.Send("panel", "page", "play-settings"); })), 0, 2); Controls.Add(outer);
        }
        void Edited() { if (rendering || !initialized || Host.Frozen) return; ++draftRevision; changed = Dirty = true; FlushEdit(); }
        public Dictionary<string, object> Raw() { var v = new Dictionary<string, object>(); var b = new Dictionary<string, object>(); foreach (var pair in values) { var check = pair.Value as CheckBox; v[pair.Key] = check == null ? (object)pair.Value.Text : check.Checked; } foreach (var pair in bindings) b[pair.Key] = pair.Value.Text; return Data.Map("values", v, "bindings", b, "draft_revision", draftRevision); }
        public void FlushEdit() { if (!initialized || !changed) return; changed = false; var raw = Raw(); Host.Send("settings_edit", "surface", "settings", "values", raw["values"], "bindings", raw["bindings"], "draft_revision", draftRevision); }
        public void Render(Dictionary<string, object> d) { if (Data.Number(d, "draft_revision") < draftRevision) return; rendering = true; try { draftRevision = Data.Number(d, "draft_revision"); var v = Data.Object(d, "values"); var b = Data.Object(d, "bindings"); foreach (var pair in values) { var check = pair.Value as CheckBox; if (check != null) check.Checked = Data.Flag(v, pair.Key); else if (pair.Value.Text != Data.Text(v, pair.Key, "")) pair.Value.Text = Data.Text(v, pair.Key, ""); } foreach (var pair in bindings) if (pair.Value.Text != Data.Text(b, pair.Key, "")) pair.Value.Text = Data.Text(b, pair.Key, ""); UI.ReplaceText(status, Data.Text(d, "status", "") + "\n\n" + Data.Text(d, "registration", "")); Dirty = Data.Flag(d, "dirty"); initialized = true; } finally { rendering = false; } }
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
            if (args.Length != 1 || args[0].Length != 32) return;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Helper(args[0]));
        }
    }
}
