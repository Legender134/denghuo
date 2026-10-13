// Fresh WPF presentation. Calculations, persistence and disclosure remain in Python.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using System.Web.Script.Serialization;
using Forms = System.Windows.Forms;

namespace Denghuo.Native {
    static class UI {
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd,int attribute,ref int value,int size);
        public static void Chrome(Window window) { window.SourceInitialized+=delegate { try { IntPtr hwnd=new WindowInteropHelper(window).Handle; int dark=1,round=2; if(DwmSetWindowAttribute(hwnd,20,ref dark,4)!=0) DwmSetWindowAttribute(hwnd,19,ref dark,4); DwmSetWindowAttribute(hwnd,33,ref round,4); } catch(DllNotFoundException) {} catch(EntryPointNotFoundException) {} }; using(var stream=typeof(UI).Assembly.GetManifestResourceStream("Denghuo.Lamp.ico")) if(stream!=null) window.Icon=BitmapFrame.Create(stream,BitmapCreateOptions.None,BitmapCacheOption.OnLoad); }
        public static Brush Background = Brush("#171A20"), Panel = Brush("#20242C"), Line = Brush("#343A45"), Ink = Brush("#F2EEE5"), Muted = Brush("#9BA3B2"), Gold = Brush("#EAC17A");
        public static SolidColorBrush Brush(string value) { return (SolidColorBrush)new BrushConverter().ConvertFromString(value); }
        public static T Name<T>(T element, string name) where T : DependencyObject { AutomationProperties.SetName(element, name); return element; }
        public static TextBlock Text(string text, double size = 13, Brush color = null) { return new TextBlock { Text = text, FontSize = size, Foreground = color ?? Ink, TextWrapping = TextWrapping.Wrap, LineHeight = size * 1.65 }; }
        public static TextBox Edit(string name, int max = 1200) { return Name(new TextBox { MaxLength = max, HorizontalAlignment = HorizontalAlignment.Stretch }, name); }
        public static Button Button(string text, Action action, bool primary = false) { var b = Name(new Button { Content = text, HorizontalContentAlignment = HorizontalAlignment.Center, Margin = new Thickness(0,0,6,6) }, text); if (primary) { b.Background = Gold; b.Foreground = Background; } b.Click += delegate { action(); }; return b; }
        public static StackPanel Stack(params UIElement[] children) { var panel = new StackPanel(); foreach (var c in children) panel.Children.Add(c); return panel; }
        public static WrapPanel Buttons(params UIElement[] children) { var panel = new WrapPanel(); foreach (var c in children) panel.Children.Add(c); return panel; }
        public static ScrollViewer Scroll(UIElement body) { return new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, CanContentScroll = false, Padding = new Thickness(0,0,4,0) }; }
        public static FrameworkElement Field(string label, FrameworkElement control, string help = "") { var title = Text(label, 12, Muted); title.Margin = new Thickness(0,0,0,6); var panel = Stack(title, control); panel.Margin = new Thickness(0,0,0,14); if (help.Length > 0) { var note = Text(help, 11, Muted); note.Margin = new Thickness(0,4,0,0); panel.Children.Add(note); AutomationProperties.SetHelpText(control, help); } return panel; }
        public static ComboBox Combo(string name, params string[] choices) { var c = Name(new ComboBox(), name); foreach (string value in choices) c.Items.Add(value); if (choices.Length > 0) c.SelectedIndex = 0; return c; }
        public static MenuItem Item(string title, Action action, bool enabled = true) { var item = new MenuItem { Header = title, IsEnabled = enabled }; item.Click += delegate { action(); }; return item; }
        public static void Menu(Button anchor, params MenuItem[] items) { var menu = new ContextMenu { PlacementTarget = anchor, Placement = PlacementMode.Bottom }; foreach (var item in items) menu.Items.Add(item); anchor.ContextMenu = menu; menu.IsOpen = true; }
        public static Expander Section(string title, UIElement body, bool expanded = false) { return Name(new Expander { Header = Text(title, 13, Gold), Content = body, IsExpanded = expanded }, title); }
        public static void Replace(TextBox field, string value) { if (field.Text == value) return; int caret = field.CaretIndex, length = field.SelectionLength; field.Text = value; field.Select(Math.Min(caret, value.Length), Math.Min(length, Math.Max(0,value.Length-caret))); }
        public static string Note(string value) { return value.Replace("\r\n", "\n").Replace("\r", "\n"); }
        public static void Fade(FrameworkElement element) { if (!SystemParameters.ClientAreaAnimation) return; element.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(.65, 1, TimeSpan.FromMilliseconds(110))); }
        public static bool InButton(DependencyObject element) { while(element!=null) { if(element is ButtonBase) return true; element=VisualTreeHelper.GetParent(element); } return false; }
        public static FrameworkElement Icon(string key, double size = 19) {
            var paths = new Dictionary<string,string> {
                {"lamp","M 8,2 L 12,2 M 10,2 L 10,5 M 6,5 L 14,5 L 16,15 L 4,15 Z M 7,18 L 13,18 M 10,8 L 8,12 L 12,12"},
                {"overview","M 2,11 L 6,11 L 9,3 L 12,17 L 15,9 L 18,9"}, {"inventory","M 5,6 L 15,6 Q 17,6 17,9 L 17,17 L 3,17 L 3,9 Q 3,6 5,6 M 7,6 L 7,3 L 13,3 L 13,6 M 7,11 L 13,11"},
                {"equipment","M 4,3 L 14,13 M 3,2 L 7,3 L 17,13 L 13,17 L 11,15 M 10,14 L 15,9 M 3,17 L 6,14"}, {"alchemy","M 7,2 L 13,2 M 8,2 L 8,8 L 3,16 Q 2,18 5,18 L 15,18 Q 18,18 17,16 L 12,8 L 12,2 M 6,12 L 14,12"},
                {"floor","M 2,16 L 18,16 M 4,16 L 4,12 L 8,12 L 8,8 L 12,8 L 12,4 L 17,4"}, {"lookup","M 3,3 L 8,3 Q 10,3 10,5 Q 10,3 12,3 L 17,3 L 17,17 L 12,17 Q 10,17 10,18 Q 10,17 8,17 L 3,17 Z M 10,5 L 10,17"},
                {"settings","M 10,2 L 12,5 L 16,4 L 16,8 L 19,10 L 16,12 L 16,16 L 12,15 L 10,18 L 8,15 L 4,16 L 4,12 L 1,10 L 4,8 L 4,4 L 8,5 Z M 13,10 A 3,3 0 1 1 7,10 A 3,3 0 1 1 13,10"},
                {"collapse","M 5,4 L 11,10 L 5,16 M 15,4 L 15,16"}, {"more","M 3,10 L 4,10 M 9,10 L 10,10 M 15,10 L 16,10"} };
            string data; if (!paths.TryGetValue(key,out data)) data = paths["more"];
            return new Viewbox { Width = size, Height = size, Child = new Path { Data = Geometry.Parse(data), Stroke = key == "lamp" ? Gold : Muted, StrokeThickness = 1.4, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, Stretch = Stretch.Uniform, Width = 20, Height = 20 } };
        }
        public static ListBoxItem Row(string text, object tag) { return Name(new ListBoxItem { Content = Text(text), Tag = tag }, text); }
        public static void Article(StackPanel body, string text) {
            body.Children.Clear();
            foreach (string paragraph in text.Replace("\r", "").Split(new[] {"\n\n"}, StringSplitOptions.RemoveEmptyEntries)) {
                int split = paragraph.IndexOf('\n');
                if (split > 0) { var title = Text(paragraph.Substring(0,split), 13, Gold); title.Margin = new Thickness(0,14,0,5); body.Children.Add(title); body.Children.Add(Text(paragraph.Substring(split+1))); }
                else { var line = Text(paragraph); line.Margin = new Thickness(0,0,0,10); body.Children.Add(line); }
            }
        }
    }

    class Dialog : Window {
        public readonly StackPanel Body = new StackPanel();
        public readonly WrapPanel Actions = new WrapPanel();
        public string Decision = "cancel";
        public bool Silent;
        public Dialog(Window owner, string title, double width = 450, double height = 440) {
            UI.Chrome(this);
            Title = "灯火 · " + title; UI.Name(this,Title); Width = width; Height = height; MinWidth = 320; MinHeight = 240; MaxWidth = SystemParameters.WorkArea.Width; MaxHeight = SystemParameters.WorkArea.Height;
            WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.CanResizeWithGrip; Background = UI.Background; Foreground = UI.Ink; FontFamily = new FontFamily("Microsoft YaHei UI"); FontSize = 13;
            WindowStartupLocation = owner != null && owner.IsVisible ? WindowStartupLocation.CenterOwner : WindowStartupLocation.CenterScreen; if (owner != null && owner.IsVisible) Owner = owner;
            var grid = new Grid { Margin = new Thickness(20) }; grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); grid.RowDefinitions.Add(new RowDefinition()); grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var header = new DockPanel { Margin = new Thickness(0,0,0,16) }; var close = UI.Button("×", delegate { Close(); }); close.ToolTip = "关闭并返回"; DockPanel.SetDock(close,Dock.Right); header.Children.Add(close); header.Children.Add(UI.Text(title,18)); header.MouseLeftButtonDown += delegate(object s,MouseButtonEventArgs e) { if (e.OriginalSource is TextBlock) DragMove(); };
            var scroll = UI.Scroll(Body); Grid.SetRow(scroll,1); Grid.SetRow(Actions,2); Actions.Margin = new Thickness(0,14,0,0); grid.Children.Add(header); grid.Children.Add(scroll); grid.Children.Add(Actions); Content = new Border { BorderBrush = UI.Line, BorderThickness = new Thickness(1), Child = grid };
            PreviewKeyDown += delegate(object s,KeyEventArgs e) { if (e.Key == Key.Escape) { Close(); e.Handled = true; } };
        }
        public void Choose(string value) { Decision = value; DialogResult = value != "cancel"; }
        public void CloseSilently() { Silent = true; Close(); }
    }

    sealed class ManagerForm : Window {
        readonly Helper Host;
        readonly Grid root = new Grid(), frame = new Grid(), workspace = new Grid();
        readonly ContentControl content = new ContentControl();
        readonly TextBlock heading = UI.Text("当前局势",20), source = UI.Text("等待游戏保存",11,UI.Muted), life = UI.Text("—",32), statistics = UI.Text("保存游戏后显示生命与局势",12,UI.Muted);
        readonly StackPanel summary = new StackPanel(), references = new StackPanel(), overview = new StackPanel(), floorBody = new StackPanel();
        readonly Dictionary<string,FrameworkElement> pages = new Dictionary<string,FrameworkElement>();
        readonly Dictionary<string,Button> navigation = new Dictionary<string,Button>();
        readonly Dictionary<string,TaskPane> tasks = new Dictionary<string,TaskPane>();
        readonly ComboBox slot = UI.Combo("存档槽位", "自动跟随", "槽位 1", "槽位 2", "槽位 3", "槽位 4", "槽位 5", "槽位 6");
        readonly CheckBox top = UI.Name(new CheckBox { Content = "独立使用时保持置顶" }, "管理窗口置顶");
        readonly ComboBox startup = UI.Combo("启动时打开","游戏助手","完整网页面板");
        readonly TextBox saveRoot = UI.Edit("当前存档目录",1000);
        readonly ScrollViewer footerScroll;
        readonly DispatcherTimer layoutTimer = new DispatcherTimer();
        readonly Button handle, more;
        public readonly TextBlock Status = UI.Text("",12,UI.Gold);
        public UIElement Editable { get { return frame; } }
        public bool Collapsed, LayoutRestored;
        public string Page = "overview";
        public double SystemDpi = 96;
        bool rendering, changingLayout = true, shutdown, attached, handleDragged;
        Rect expandedBounds = new Rect(0,0,480,600), gameBounds;
        int gameX = 16, gameY = 16;
        Point dragStart, dragLocation;
        string floorToken = "", floorSignature = "";
        readonly Dictionary<string,bool> floorExpanded = new Dictionary<string,bool>();
        public IntPtr Handle { get { return new WindowInteropHelper(this).Handle; } }
        public bool Visible { get { return IsVisible; } }
        public bool TasksDirty { get { foreach (var pane in tasks.Values) if (pane.Dirty) return true; return false; } }
        public Dictionary<string,object> TaskRaw() { var raw = new Dictionary<string,object>(); foreach (var pair in tasks) if (pair.Value.Dirty) raw[pair.Key] = pair.Value.Raw(); return raw; }
        public void FlushTasks() { foreach (var pane in tasks.Values) if (pane.Dirty) pane.Flush(); }
        public void SetTaskPlanMetadata(string page,string name,string note) { if(tasks.ContainsKey(page)) tasks[page].SetPlanMetadata(name,note); }
        public void RenderTask(Dictionary<string,object> data) { string page = Data.Text(data,"page",""); if (tasks.ContainsKey(page)) tasks[page].Render(data); }
        public ManagerForm(Helper host) {
            UI.Chrome(this);
            Host = host; Title = "灯火 · 游戏助手"; UI.Name(this,Title); Width = 480; Height = 600; MinWidth = 340; MinHeight = 360; MaxWidth = MaxHeight = 2400; Background = UI.Background; Foreground = UI.Ink; FontFamily = new FontFamily("Microsoft YaHei UI"); FontSize = 13;
            WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.CanResize; ShowActivated = false; UseLayoutRounding = true; SnapsToDevicePixels = true;
            Left = SystemParameters.WorkArea.Right-Width-16; Top = SystemParameters.WorkArea.Top+40;
            frame.RowDefinitions.Add(new RowDefinition { Height = new GridLength(52) }); frame.RowDefinitions.Add(new RowDefinition()); frame.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var chrome = new Grid { Background = UI.Background, Margin = new Thickness(15,0,10,0) }; chrome.ColumnDefinitions.Add(new ColumnDefinition()); chrome.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var brand = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center }; brand.Children.Add(UI.Icon("lamp",21)); var brandText = UI.Text("灯火",15); brandText.Margin = new Thickness(9,0,10,0); brand.Children.Add(brandText); var tag = UI.Text("游戏助手",10,UI.Muted); tag.VerticalAlignment = VerticalAlignment.Center; brand.Children.Add(tag); chrome.Children.Add(brand);
            chrome.MouseLeftButtonDown += delegate(object s,MouseButtonEventArgs e) { if (!UI.InButton(e.OriginalSource as DependencyObject)) { DragMove(); SaveLayout(); } };
            var tools = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center }; var compact = UI.Button("",delegate { Collapse(); }); compact.Content = UI.Icon("collapse",17); UI.Name(compact,"收起灯火助手"); compact.ToolTip = "收起 · 保留当前工作"; compact.Background = Brushes.Transparent;
            more = UI.Button("",ShowMore); more.Content = UI.Icon("more",18); UI.Name(more,"更多操作"); more.ToolTip = "更多 · 窗口与工具"; more.Background = Brushes.Transparent; tools.Children.Add(compact); tools.Children.Add(more); Grid.SetColumn(tools,1); chrome.Children.Add(tools); frame.Children.Add(chrome);
            workspace.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(62) }); workspace.ColumnDefinitions.Add(new ColumnDefinition()); Grid.SetRow(workspace,1);
            var rail = new StackPanel { Margin = new Thickness(7,4,7,0) }; var railScroll = UI.Scroll(rail); railScroll.Padding = new Thickness(0); workspace.Children.Add(railScroll);
            foreach (string[] pair in new[] {new[]{"overview","局势"},new[]{"inventory","背包"},new[]{"equipment","装备"},new[]{"alchemy","炼金"},new[]{"floor","本层"},new[]{"lookup","数值"},new[]{"settings","设置"}}) {
                string key = pair[0]; var icon = UI.Icon(key); var name = UI.Text(pair[1],10,UI.Muted); name.HorizontalAlignment = HorizontalAlignment.Center; name.Margin = new Thickness(0,5,0,0); var inside = UI.Stack(icon,name); icon.HorizontalAlignment = HorizontalAlignment.Center;
                var button = UI.Button("",delegate { OpenPage(key); }); button.Content = inside; button.Padding = new Thickness(5,10,5,8); button.Margin = new Thickness(0,0,0,4); button.Background = Brushes.Transparent; button.ToolTip = pair[1]; UI.Name(button,pair[1]); rail.Children.Add(button); navigation[key] = button;
            }
            var area = new Grid { Margin = new Thickness(12,5,16,8) }; area.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); area.RowDefinitions.Add(new RowDefinition()); heading.Margin = new Thickness(0,0,0,14); area.Children.Add(heading); Grid.SetRow(content,1); area.Children.Add(content); Grid.SetColumn(area,1); workspace.Children.Add(area); frame.Children.Add(workspace);
            var footer = new StackPanel { Margin = new Thickness(16,7,20,10) }; footer.Children.Add(source); Status.Margin = new Thickness(0,5,0,0); Status.Visibility = Visibility.Collapsed; footer.Children.Add(Status); footerScroll = UI.Scroll(footer); footerScroll.MaxHeight = 80; Grid.SetRow(footerScroll,2); frame.Children.Add(footerScroll);
            var grip = UI.Name(new Thumb { Width = 18, Height = 18, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Bottom, Cursor = Cursors.SizeNWSE, ToolTip = "拖动调整窗口大小" }, "调整窗口大小");
            var gripArea = new FrameworkElementFactory(typeof(Border)); gripArea.SetValue(Border.BackgroundProperty,Brushes.Transparent); var gripVisual = new FrameworkElementFactory(typeof(Path)); gripVisual.SetValue(Path.DataProperty,Geometry.Parse("M 6,16 L 16,6 M 11,16 L 16,11")); gripVisual.SetValue(Path.StrokeProperty,UI.Muted); gripVisual.SetValue(Path.StrokeThicknessProperty,1.0); gripArea.AppendChild(gripVisual); grip.Template = new ControlTemplate(typeof(Thumb)) { VisualTree = gripArea };
            grip.DragDelta += delegate(object sender,DragDeltaEventArgs e) { if (Host.Frozen) return; Width = Math.Max(MinWidth,Math.Min(MaxWidth,Width+e.HorizontalChange)); Height = Math.Max(MinHeight,Math.Min(MaxHeight,Height+e.VerticalChange)); }; grip.DragCompleted += delegate { ClampBounds(); SaveLayout(); }; Grid.SetRow(grip,2); frame.Children.Add(grip);
            overview.Children.Add(UI.Text("生命",11,UI.Muted)); overview.Children.Add(life); statistics.Margin = new Thickness(0,0,0,20); overview.Children.Add(statistics); overview.Children.Add(summary); overview.Children.Add(references); overview.Children.Add(UI.Buttons(UI.Button("立即备份",delegate { Host.Send("capture"); },true), UI.Button("刷新存档",delegate { Host.Send("refresh"); })));
            pages["overview"] = UI.Scroll(overview); pages["floor"] = UI.Scroll(floorBody);
            foreach (string page in new[]{"inventory","equipment","alchemy","character","map","backups"}) { var pane = new TaskPane(Host,page); tasks[page] = pane; pages[page] = pane; }
            handle = UI.Button("",delegate { Expand(); Activate(); }); handle.Content = UI.Stack(UI.Icon("lamp",19),UI.Text("›",15,UI.Gold)); handle.ToolTip = "展开灯火 · 拖动可移动"; UI.Name(handle,"展开灯火助手"); handle.Margin = new Thickness(0); handle.Padding = new Thickness(7,10,7,8); handle.Background = UI.Panel; handle.Visibility = Visibility.Collapsed;
            handle.PreviewMouseLeftButtonDown += delegate { dragStart = PointToScreen(Mouse.GetPosition(this)); dragLocation = new Point(Left,Top); handleDragged = false; handle.CaptureMouse(); };
            handle.PreviewMouseMove += delegate { if (Mouse.LeftButton != MouseButtonState.Pressed || !handle.IsMouseCaptured) return; Point p = PointToScreen(Mouse.GetPosition(this)); double scale = SystemDpi/96; if ((p-dragStart).Length > 6) { handleDragged = true; Left = dragLocation.X+(p.X-dragStart.X)/scale; Top = dragLocation.Y+(p.Y-dragStart.Y)/scale; } };
            handle.PreviewMouseLeftButtonUp += delegate(object s,MouseButtonEventArgs e) { handle.ReleaseMouseCapture(); if (handleDragged) { expandedBounds.X = Left; expandedBounds.Y = Top; ClampBounds(); SaveLayout(); } else { Expand(); Activate(); } e.Handled = true; };
            var handleMenu = new ContextMenu(); handleMenu.Items.Add(UI.Item("展开灯火",delegate { Expand(); Activate(); })); handleMenu.Items.Add(UI.Item("恢复默认大小与位置",ResetLayout)); handleMenu.Items.Add(UI.Item("退出灯火",delegate { Host.Send("exit"); })); handle.ContextMenu = handleMenu;
            root.Children.Add(frame); root.Children.Add(handle); Content = new Border { BorderBrush = UI.Line, BorderThickness = new Thickness(1), Child = root };
            slot.SelectionChanged += delegate { if (!rendering && !Host.Frozen) Host.Send("slot","index",slot.SelectedIndex); }; top.Checked += delegate { PinChanged(); }; top.Unchecked += delegate { PinChanged(); };
            SourceInitialized += delegate { var hwndSource = HwndSource.FromHwnd(Handle); if (hwndSource != null) { SystemDpi = 96*hwndSource.CompositionTarget.TransformToDevice.M11; hwndSource.AddHook(WindowMessage); } };
            layoutTimer.Interval = TimeSpan.FromMilliseconds(250); layoutTimer.Tick += delegate { layoutTimer.Stop(); SaveLayout(); }; SizeChanged += delegate { bool small=ActualHeight<480 && !Collapsed; frame.RowDefinitions[0].Height=new GridLength(small ? 40 : 52); heading.FontSize=small ? 16 : 20; heading.Margin=new Thickness(0,0,0,small ? 6 : 14); footerScroll.MaxHeight=small ? 44 : 80; QueueLayout(); }; LocationChanged += delegate { QueueLayout(); };
            IsVisibleChanged += delegate { Host.VisibilityAll(); }; Closing += delegate(object s,CancelEventArgs e) { if (!shutdown) { e.Cancel = true; Collapse(); } };
            KeyDown += delegate(object s,KeyEventArgs e) { if (e.Key == Key.Escape && !Host.Frozen) { Collapse(); e.Handled = true; } };
            PreviewKeyDown += delegate(object s,KeyEventArgs e) { if (e.Key == Key.F1) Host.Send("panel","page","help"); if (e.Key == Key.F && Keyboard.Modifiers == ModifierKeys.Control) { Host.ShowSurface("lookup"); Host.Lookup.FocusSearch(); e.Handled = true; } };
            new WindowInteropHelper(this).EnsureHandle(); expandedBounds = new Rect(Left,Top,Width,Height);
        }
        IntPtr WindowMessage(IntPtr hwnd,int msg,IntPtr wParam,IntPtr lParam,ref bool handled) {
            if (msg == 0x84 && !Collapsed) { long value = lParam.ToInt64(); int x = (short)(value&65535), y = (short)((value>>16)&65535); Point p = PointFromScreen(new Point(x,y)); bool left = p.X < 6, right = p.X > ActualWidth-6, topEdge = p.Y < 6, bottom = p.Y > ActualHeight-6; int hit = topEdge ? left ? 13 : right ? 14 : 12 : bottom ? left ? 16 : right ? 17 : 15 : left ? 10 : right ? 11 : 0; if (hit != 0) { handled = true; return new IntPtr(hit); } }
            return IntPtr.Zero;
        }
        void PinChanged() { if (!rendering && !Host.Frozen) Host.Send("pin_manager","checked",top.IsChecked == true); }
        public void Mount(string page,FrameworkElement pane) { if (page == "settings") {
            saveRoot.IsReadOnly=true; saveRoot.TextWrapping=TextWrapping.Wrap; saveRoot.AcceptsReturn=true;
            startup.SelectionChanged+=delegate { if(!rendering && !Host.Frozen) Host.Send("startup_surface","value",startup.SelectedIndex==0 ? "native" : "panel"); };
            var connection = UI.Stack(UI.Field("当前存档目录（可选择复制）",saveRoot),UI.Field("存档槽位",slot),top,UI.Field("启动时打开",startup),UI.Buttons(UI.Button("选择存档目录…",delegate { using (var picker = new Forms.FolderBrowserDialog { Description = "选择包含 game1、game2 等文件夹的存档目录", SelectedPath=saveRoot.Text, ShowNewFolderButton = false }) { if (picker.ShowDialog(new NativeOwner(Handle)) == Forms.DialogResult.OK) Host.Send("directory","path",picker.SelectedPath); } }),UI.Button("刷新存档",delegate { Host.Send("refresh"); }),UI.Button("重新读取连接设置",delegate { Host.Send("reload_connection"); })));
            Host.Settings.Connection = connection; Host.Settings.Prepend(connection); pages[page] = pane;
        } else pages[page] = pane; }
        public void OpenPage(string page) { if (Host.Frozen) return; if (page == "lookup") Host.Send("show_lookup"); else if (page == "settings") Host.Send("show_settings"); else if (page == "plans") Host.Send("choose_plan","surface","lookup"); else if (page != "overview" && page != "floor") Host.Send("game_page","page",page); ShowPage(page); }
        public void ShowPage(string page) { if (!pages.ContainsKey(page)) return; bool changed = Page != page; if(Page=="inventory" && page!="inventory") Host.Send("leave_inventory"); Page = page; content.Content = pages[page]; var names = new Dictionary<string,string> {{"overview","当前局势"},{"inventory","随身背包"},{"equipment","装备比较"},{"alchemy","炼金规划"},{"floor","本层指南"},{"lookup","数值手册"},{"character","角色条件"},{"map","保存地图"},{"backups","存档历史"},{"plans","我的方案"},{"settings","游玩设置"}}; heading.Text = names[page]; foreach (var pair in navigation) pair.Value.Background = pair.Key == page ? UI.Brush("#353027") : Brushes.Transparent; if (changed) UI.Fade(content); Host.VisibilityAll(); if (!changingLayout) SaveLayout(); }
        void ShowMore() { UI.Menu(more,UI.Item("角色条件",delegate { OpenPage("character"); }),UI.Item("保存地图",delegate { OpenPage("map"); }),UI.Item("存档历史",delegate { OpenPage("backups"); }),UI.Item("我的方案",delegate { OpenPage("plans"); }),UI.Item("找回未完成草稿",delegate { Host.Send("list_drafts"); }),UI.Item("恢复默认大小与位置",ResetLayout),UI.Item("完整面板",delegate { Host.Send("panel","page","overview"); }),UI.Item("退出灯火",delegate { Host.Send("exit"); })); }
        void QueueLayout() { if (!changingLayout) { layoutTimer.Stop(); layoutTimer.Start(); } }
        void ClampBounds() { var scale = SystemDpi/96; var area = Forms.Screen.FromRectangle(new System.Drawing.Rectangle((int)(Left*scale),(int)(Top*scale),(int)(Width*scale),(int)(Height*scale))).WorkingArea; double x=area.Left/scale,y=area.Top/scale,w=area.Width/scale,h=area.Height/scale; Width = Math.Min(Width,w); Height = Math.Min(Height,h); Left = Math.Max(x,Math.Min(Left,x+w-Width)); Top = Math.Max(y,Math.Min(Top,y+h-Height)); }
        public void Collapse() { if (Collapsed) return; changingLayout = true; if (WindowState != WindowState.Normal) WindowState = WindowState.Normal; expandedBounds = new Rect(Left,Top,Width,Height); Collapsed = true; frame.Visibility = Visibility.Collapsed; MinWidth = MinHeight = 0; ResizeMode = ResizeMode.NoResize; Width = 36; Height = 68; handle.Visibility = Visibility.Visible; ClampBounds(); changingLayout = false; SaveLayout(); Host.VisibilityAll(); }
        public void Expand() { if (!Collapsed) return; changingLayout = true; Collapsed = false; handle.Visibility = Visibility.Collapsed; MinWidth = 340; MinHeight = 360; ResizeMode = ResizeMode.CanResize; Left=expandedBounds.X; Top=expandedBounds.Y; Width=expandedBounds.Width; Height=expandedBounds.Height; frame.Visibility = Visibility.Visible; ClampBounds(); changingLayout = false; SaveLayout(); Host.VisibilityAll(); }
        public void SaveLayout(bool reset = false) { if (changingLayout) return; LayoutRestored = true; Rect normal = Collapsed ? expandedBounds : new Rect(Left,Top,Width,Height); if (attached) { gameX = (int)Math.Round(Left-gameBounds.Left); gameY = (int)Math.Round(Top-gameBounds.Top); } Host.Send(reset ? "layout_reset" : "window_layout","layout",Data.Map("width",Math.Max(340,(int)Math.Round(normal.Width)),"height",Math.Max(360,(int)Math.Round(normal.Height)),"x",(int)Math.Round(normal.X),"y",(int)Math.Round(normal.Y),"game_x",gameX,"game_y",gameY,"collapsed",Collapsed,"page",Page)); }
        public void ApplyLayout(Dictionary<string,object> d) { changingLayout = true; bool collapsed = Data.Flag(d,"collapsed"); gameX=(int)Data.Number(d,"game_x"); gameY=(int)Data.Number(d,"game_y"); Width=Math.Max(340,Data.Number(d,"width")); Height=Math.Max(360,Data.Number(d,"height")); if (d.ContainsKey("x") && d["x"] != null) { Left=Data.Number(d,"x"); Top=Data.Number(d,"y"); } ClampBounds(); expandedBounds=new Rect(Left,Top,Width,Height); ShowPage(Data.Text(d,"page","overview")); changingLayout=false; if (collapsed) Collapse(); }
        void ResetLayout() { bool collapsed=Collapsed; Expand(); changingLayout=true; Width=480; Height=600; gameX=gameY=16; Left=attached ? gameBounds.Left+16 : SystemParameters.WorkArea.Right-Width-16; Top=attached ? gameBounds.Top+16 : SystemParameters.WorkArea.Top+40; ClampBounds(); expandedBounds=new Rect(Left,Top,Width,Height); changingLayout=false; if (collapsed) Collapse(); SaveLayout(true); }
        public void FollowGame(Dictionary<string,object> d) { var rect=Data.Array(d,"rect"); if (rect.Length==4) { bool first=!attached; double scale=SystemDpi/96; gameBounds=new Rect(Convert.ToDouble(rect[0])/scale,Convert.ToDouble(rect[1])/scale,(Convert.ToDouble(rect[2])-Convert.ToDouble(rect[0]))/scale,(Convert.ToDouble(rect[3])-Convert.ToDouble(rect[1]))/scale); attached=true; changingLayout=true; Left=gameBounds.Left+gameX; Top=gameBounds.Top+gameY; expandedBounds.X=Left; expandedBounds.Y=Top; ClampBounds(); changingLayout=false; Topmost=true; if(first && !LayoutRestored) Collapse(); } else { attached=false; Topmost=top.IsChecked==true; } if(attached) { if(Data.Flag(d,"visible") && !IsVisible) Show(); else if(!Data.Flag(d,"visible") && IsVisible) Hide(); Host.VisibilityAll(); } }
        public void CloseForShutdown() { shutdown=true; layoutTimer.Stop(); Close(); }
        public void Error(string text) { Status.Text=text; Status.Visibility=String.IsNullOrEmpty(text) ? Visibility.Collapsed : Visibility.Visible; }
        void FloorNodes(StackPanel parent,object[] nodes,string path) { foreach(object raw in nodes) { var row=raw as Dictionary<string,object>; if(row==null) continue; string id=Data.Text(row,"id", ""), identity=path+"/"+id; var children=Data.Array(row,"children"); var body=new StackPanel(); string detail=Data.Text(row,"detail",""); if(detail.Length>0) body.Children.Add(UI.Text(detail,12,UI.Muted)); if(identity.StartsWith("/monsters/") && (id.StartsWith("actors.mobs.") || id.StartsWith("levels.") || id.StartsWith("items.quest."))) body.Children.Add(UI.Button("查看数值",delegate { Host.Send("floor_reference","id",id,"token",floorToken); })); if(identity.StartsWith("/hidden/") && id.StartsWith("item-floor-")) body.Children.Add(UI.Button("查看物品数值",delegate { Host.Send("floor_item_reference","id",id,"token",floorToken); })); FloorNodes(body,children,identity); if(body.Children.Count>0) { bool expanded; if(!floorExpanded.TryGetValue(identity,out expanded)) expanded=Data.Flag(row,"expanded"); var section=UI.Section(Data.Text(row,"text",""),body,expanded); section.Expanded+=delegate { floorExpanded[identity]=true; }; section.Collapsed+=delegate { floorExpanded[identity]=false; }; parent.Children.Add(section); } else { var text=UI.Text(Data.Text(row,"text","")); text.Margin=new Thickness(0,0,0,8); parent.Children.Add(text); } } }
        public void Render(Dictionary<string,object> d) { rendering=true; try { life.Text=Data.Text(d,"life","等待有效存档").Replace("  生命",""); statistics.Text=Data.Text(d,"statistics",""); source.Text=Data.Text(d,"source","等待游戏保存"); Error(Data.Text(d,"error","")); UI.Article(summary,Data.Text(d,"text","")); references.Children.Clear(); var tokens=Data.Array(d,"reference_tokens"); int index=0; foreach(object raw in Data.Array(d,"references")) { int selected=index++; string token=selected<tokens.Length ? Convert.ToString(tokens[selected]) : ""; var button=UI.Button(Convert.ToString(raw),delegate { Host.Send("reference","index",selected,"token",token); }); button.HorizontalContentAlignment=HorizontalAlignment.Left; references.Children.Add(button); } UI.Replace(saveRoot,Data.Text(d,"save_root","")); startup.SelectedIndex=Data.Text(d,"startup_surface","native")=="native" ? 0 : 1; slot.SelectedIndex=(int)Math.Max(0,Math.Min(6,Data.Number(d,"slot"))); top.IsChecked=Data.Flag(d,"topmost"); if(!attached) Topmost=top.IsChecked==true; if(Host.Settings!=null && Host.Settings.Connection!=null) Host.Settings.Connection.IsEnabled=!Data.Flag(d,"io_busy");
            var guide=Data.Object(d,"floor_guide"); floorToken=Data.Text(guide,"token",""); string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(guide); if(signature!=floorSignature) { floorBody.Children.Clear(); floorBody.Children.Add(UI.Text(Data.Text(guide,"caption","当前楼层"),12,UI.Muted)); var reveal=UI.Button(Data.Flag(guide,"revealed") ? "收起隐藏内容" : "主动揭示隐藏内容",delegate { Host.Send("reveal_floor","token",floorToken); }); reveal.IsEnabled=Data.Flag(guide,"enabled"); floorBody.Children.Add(reveal); FloorNodes(floorBody,Data.Array(guide,"nodes"),""); floorSignature=signature; }
        } finally { rendering=false; } }
    }
    sealed class NativeOwner : Forms.IWin32Window { readonly IntPtr hwnd; public NativeOwner(IntPtr value) { hwnd=value; } public IntPtr Handle { get { return hwnd; } } }
}
