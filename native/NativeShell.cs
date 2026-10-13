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
    static class GameFocus {
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd,int command);
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd,System.Text.StringBuilder text,int maximum);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd,System.Text.StringBuilder text,int maximum);
        public static bool OwnsForeground(Dictionary<string,object> game) {
            var hwnd=new IntPtr(Data.Number(game,"hwnd")); uint pid;
            GetWindowThreadProcessId(hwnd,out pid);
            return hwnd!=IntPtr.Zero && pid==(uint)Data.Number(game,"pid") && GetForegroundWindow()==hwnd;
        }
        public static bool Return(Dictionary<string,object> game) {
            // Only the foreground helper may yield focus, and only to the verified game.
            uint foregroundPid,gamePid;
            GetWindowThreadProcessId(GetForegroundWindow(),out foregroundPid);
            if(foregroundPid!=(uint)System.Diagnostics.Process.GetCurrentProcess().Id) return false;
            var hwnd=new IntPtr(Data.Number(game,"hwnd")); uint expected=(uint)Data.Number(game,"pid");
            if(hwnd==IntPtr.Zero || expected==0 || !IsWindow(hwnd)) return false;
            GetWindowThreadProcessId(hwnd,out gamePid); if(gamePid!=expected) return false;
            var title=new System.Text.StringBuilder(512); var kind=new System.Text.StringBuilder(128);
            GetWindowText(hwnd,title,title.Capacity); GetClassName(hwnd,kind,kind.Capacity);
            if(!title.ToString().StartsWith("Shattered Pixel Dungeon",StringComparison.Ordinal) ||
                kind.ToString()!="GLFW30" && kind.ToString()!="LWJGL") return false;
            if(IsIconic(hwnd)) ShowWindow(hwnd,9);
            return SetForegroundWindow(hwnd) && GetForegroundWindow()==hwnd;
        }
    }
    static class UI {
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd,int attribute,ref int value,int size);
        public static void Chrome(Window window) { window.SourceInitialized+=delegate { try { IntPtr hwnd=new WindowInteropHelper(window).Handle; int dark=0,round=2; if(DwmSetWindowAttribute(hwnd,20,ref dark,4)!=0) DwmSetWindowAttribute(hwnd,19,ref dark,4); DwmSetWindowAttribute(hwnd,33,ref round,4); } catch(DllNotFoundException) {} catch(EntryPointNotFoundException) {} }; using(var stream=typeof(UI).Assembly.GetManifestResourceStream("Denghuo.Lamp.ico")) if(stream!=null) window.Icon=BitmapFrame.Create(stream,BitmapCreateOptions.None,BitmapCacheOption.OnLoad); }
        public static Brush Background = Brush("#F7F3E8"), Panel = Brush("#FFFDF7"), Line = Brush("#DDD5C5"), Ink = Brush("#2F342F"), Muted = Brush("#666A60"), Gold = Brush("#865D28");
        public static SolidColorBrush Brush(string value) { return (SolidColorBrush)new BrushConverter().ConvertFromString(value); }
        public static T Name<T>(T element, string name) where T : DependencyObject { AutomationProperties.SetName(element, name); return element; }
        public static TextBlock Text(string text, double size = 14, Brush color = null) { return new TextBlock { Text = text, FontFamily = new FontFamily("Segoe UI, Microsoft YaHei UI, Microsoft YaHei"), FontSize = size, Foreground = color ?? Ink, TextWrapping = TextWrapping.Wrap, LineHeight = size * 1.5 }; }
        public static TextBox Edit(string name, int max = 1200) { return Name(new TextBox { MaxLength = max, HorizontalAlignment = HorizontalAlignment.Stretch }, name); }
        public static Button Button(string text, Action action, bool primary = false) { var b = Name(new Button { Content = text, HorizontalContentAlignment = HorizontalAlignment.Center, Margin = new Thickness(0,0,6,6) }, text); if (primary) { b.Background = Gold; b.Foreground = Background; } b.Click += delegate { action(); }; return b; }
        public static StackPanel Stack(params UIElement[] children) { var panel = new StackPanel(); foreach (var c in children) panel.Children.Add(c); return panel; }
        public static WrapPanel Buttons(params UIElement[] children) { var panel = new WrapPanel(); foreach (var c in children) panel.Children.Add(c); return panel; }
        public static ScrollViewer Scroll(UIElement body) { return new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, CanContentScroll = false, Padding = new Thickness(0,0,4,0) }; }
        public static FrameworkElement Field(string label, FrameworkElement control, string help = "") { var title = Text(label, 12, Muted); title.Margin = new Thickness(0,0,0,6); var panel = Stack(title, control); panel.Margin = new Thickness(0,0,0,14); if (help.Length > 0) { var note = Text(help, 11, Muted); note.Margin = new Thickness(0,4,0,0); panel.Children.Add(note); AutomationProperties.SetHelpText(control, help); } return panel; }
        public static ComboBox Combo(string name, params string[] choices) { var c = Name(new ComboBox(), name); foreach (string value in choices) c.Items.Add(value); if (choices.Length > 0) c.SelectedIndex = 0; return c; }
        public static MenuItem Item(string title, Action action, bool enabled = true) { var item = new MenuItem { Header = title, IsEnabled = enabled }; item.Click += delegate { action(); }; return item; }
        public static void Menu(Button anchor, params object[] items) { if(anchor.ContextMenu!=null) anchor.ContextMenu.IsOpen=false; var menu=new ContextMenu(); menu.PlacementTarget = anchor; menu.Placement = PlacementMode.Bottom; foreach (var item in items) menu.Items.Add(item); anchor.ContextMenu = menu; menu.Closed+=delegate { if(anchor.IsVisible && anchor.IsEnabled) anchor.Focus(); }; menu.IsOpen = true; }
        public static Expander Section(string title, UIElement body, bool expanded = false) { return Name(new Expander { Header = Text(title, 13, Gold), Content = body, IsExpanded = expanded }, title); }
        public static void Replace(TextBox field, string value) { if (field.Text == value) return; int caret = field.CaretIndex, length = field.SelectionLength; field.Text = value; field.Select(Math.Min(caret, value.Length), Math.Min(length, Math.Max(0,value.Length-caret))); }
        public static string Note(string value) { return value.Replace("\r\n", "\n").Replace("\r", "\n"); }
        public static void Fade(FrameworkElement element) { if (!SystemParameters.ClientAreaAnimation) return; element.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(.65, 1, TimeSpan.FromMilliseconds(110))); }
        public static bool InButton(DependencyObject element) { while(element!=null) { if(element is ButtonBase) return true; element=VisualTreeHelper.GetParent(element); } return false; }
        public static FrameworkElement Icon(string key, double size = 19, Brush color = null) {
            if(key=="lamp") {
                var canvas=new Canvas { Width=64, Height=64 };
                foreach(string shape in new[]{"M24 14h16v5h5v6H19v-6h5z M17 28h6v21h18V28h6v26H17z", "M29 27h6v6h5v11H24V33h5z", "M28 36h8v9h-8z", "M25 57h14v3H25z"})
                    canvas.Children.Add(new Path { Data=Geometry.Parse(shape), Fill=color ?? Gold });
                return new Viewbox { Width=size, Height=size, Child=canvas };
            }
            var paths = new Dictionary<string,string> {
                {"lamp","M 8,2 L 12,2 M 10,2 L 10,5 M 6,5 L 14,5 L 16,15 L 4,15 Z M 7,18 L 13,18 M 10,8 L 8,12 L 12,12"},
                {"overview","M 2,11 L 6,11 L 9,3 L 12,17 L 15,9 L 18,9"}, {"inventory","M 5,6 L 15,6 Q 17,6 17,9 L 17,17 L 3,17 L 3,9 Q 3,6 5,6 M 7,6 L 7,3 L 13,3 L 13,6 M 7,11 L 13,11"},
                {"equipment","M 4,3 L 14,13 M 3,2 L 7,3 L 17,13 L 13,17 L 11,15 M 10,14 L 15,9 M 3,17 L 6,14"}, {"alchemy","M 7,2 L 13,2 M 8,2 L 8,8 L 3,16 Q 2,18 5,18 L 15,18 Q 18,18 17,16 L 12,8 L 12,2 M 6,12 L 14,12"},
                {"floor","M 2,16 L 18,16 M 4,16 L 4,12 L 8,12 L 8,8 L 12,8 L 12,4 L 17,4"}, {"lookup","M 3,3 L 8,3 Q 10,3 10,5 Q 10,3 12,3 L 17,3 L 17,17 L 12,17 Q 10,17 10,18 Q 10,17 8,17 L 3,17 Z M 10,5 L 10,17"},
                {"settings","M 10,2 L 12,5 L 16,4 L 16,8 L 19,10 L 16,12 L 16,16 L 12,15 L 10,18 L 8,15 L 4,16 L 4,12 L 1,10 L 4,8 L 4,4 L 8,5 Z M 13,10 A 3,3 0 1 1 7,10 A 3,3 0 1 1 13,10"},
                {"collapse","M 5,4 L 11,10 L 5,16 M 15,4 L 15,16"}, {"reset","M 3,9 A 7,7 0 1 1 5,16 M 3,3 L 3,9 L 9,9"}, {"more","M 3,10 L 4,10 M 9,10 L 10,10 M 15,10 L 16,10"} };
            string data; if (!paths.TryGetValue(key,out data)) data = paths["more"];
            return new Viewbox { Width = size, Height = size, Child = new Path { Data = Geometry.Parse(data), Stroke = color ?? (key == "lamp" ? Gold : Muted), StrokeThickness = 1.4, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, Stretch = Stretch.Uniform, Width = 20, Height = 20 } };
        }
        public static ListBoxItem Row(string text, object tag) { return Name(new ListBoxItem { Content = Text(text), Tag = tag }, text); }
        static readonly Dictionary<string,BitmapSource> artworkCache = new Dictionary<string,BitmapSource>();
        public static FrameworkElement Artwork(Dictionary<string,object> data, double size = 34) {
            string encoded=Data.Text(data,"png",""), key=Data.Text(data,"sha256","");
            if(encoded.Length==0 || encoded.Length>12000 || key.Length!=64) return new Border { Width=0 };
            BitmapSource bitmap;
            if(!artworkCache.TryGetValue(key,out bitmap)) {
                try { byte[] bytes=Convert.FromBase64String(encoded); var image=new BitmapImage(); using(var stream=new System.IO.MemoryStream(bytes)) { image.BeginInit(); image.CacheOption=BitmapCacheOption.OnLoad; image.StreamSource=stream; image.EndInit(); } if(image.PixelWidth>256 || image.PixelHeight>256) return new Border { Width=0 }; image.Freeze(); bitmap=image; artworkCache[key]=bitmap; }
                catch(FormatException) { return new Border { Width=0 }; } catch(System.IO.IOException) { return new Border { Width=0 }; } catch(NotSupportedException) { return new Border { Width=0 }; }
            }
            var picture=new Image { Source=bitmap, Width=Math.Min(size,bitmap.PixelWidth*2), Height=Math.Min(size,bitmap.PixelHeight*2), Stretch=Stretch.Uniform, HorizontalAlignment=HorizontalAlignment.Center, VerticalAlignment=VerticalAlignment.Center };
            RenderOptions.SetBitmapScalingMode(picture,BitmapScalingMode.NearestNeighbor);
            return Name(new Border { Width=size+10, Height=size+10, Background=Brush("#EEE9DA"), CornerRadius=new CornerRadius(6), Margin=new Thickness(0,0,10,0), Child=picture, ToolTip=Data.Text(data,"alt","")+"\n"+Data.Text(data,"caption","") },Data.Text(data,"alt","游戏图像"));
        }
        public static FrameworkElement ImageRow(string title, Dictionary<string,object> data, bool heading = false) {
            var row=new DockPanel { LastChildFill=true }; var picture=Artwork(data,heading ? 38 : 26); DockPanel.SetDock(picture,Dock.Left); row.Children.Add(picture); var words=Stack(Text(title,heading ? 17 : 13)); words.VerticalAlignment=VerticalAlignment.Center;
            if(heading) ((TextBlock)words.Children[0]).FontWeight=FontWeights.SemiBold;
            row.Children.Add(words); return row;
        }
        public static Border Card(UIElement body, bool highlighted = false) { return new Border { Child=body, Background=highlighted ? Brush("#F0E6CF") : Panel, BorderBrush=Line, BorderThickness=new Thickness(1), CornerRadius=new CornerRadius(9), Padding=new Thickness(14), Margin=new Thickness(0,0,0,12) }; }
        public static void IllustratedArticle(StackPanel body,string text,Dictionary<string,object> artwork) {
            if(artwork.Count==0) { Article(body,text); return; }
            int split=text.IndexOf('\n'); string title=split<0 ? text : text.Substring(0,split); Article(body,split<0 ? "" : text.Substring(split+1)); var heading=ImageRow(title,artwork,true); heading.Margin=new Thickness(0,0,0,12); body.Children.Insert(0,heading);
        }
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
            WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.CanResizeWithGrip; Background = UI.Background; Foreground = UI.Ink; FontFamily = new FontFamily("Segoe UI, Microsoft YaHei UI, Microsoft YaHei"); FontSize = 13;
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
        readonly TextBlock heading = UI.Text("提示",16), source = UI.Text("等待游戏保存",12,UI.Muted), sourceBrief = UI.Text("等待存档",12,UI.Muted), protection = UI.Text("等待备份",12,UI.Muted), life = UI.Text("",12,UI.Muted), statistics = UI.Text("",12,UI.Muted);
        readonly StackPanel summary = new StackPanel(), overview = new StackPanel(), floorBody = new StackPanel();
        readonly TextBlock snapshotNotes = UI.Text("",12,UI.Muted);
        readonly Expander sourceDetails;
        readonly Dictionary<string,FrameworkElement> pages = new Dictionary<string,FrameworkElement>();
        readonly Dictionary<string,Button> navigation = new Dictionary<string,Button>();
        readonly Dictionary<string,TextBlock> navigationLabels = new Dictionary<string,TextBlock>();
        readonly List<FrameworkElement> navigationGlyphs = new List<FrameworkElement>();
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
        Rect expandedBounds = new Rect(0,0,380,460), gameBounds;
        int gameX = 16, gameY = 16;
        Point dragStart, dragLocation;
        IInputElement workFocus;
        string floorToken = "", floorSignature = "", floorOwner = "";
        readonly Dictionary<string,UIElement> floorControls = new Dictionary<string,UIElement>();
        Button floorReveal;
        string overviewText = null; bool overviewDetailsExpanded;
        readonly Dictionary<string,bool> insightExpanded = new Dictionary<string,bool>();
        readonly Dictionary<string,UIElement> insightControls = new Dictionary<string,UIElement>();
        object[] overviewTokens = new object[0];
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
            Host = host; Title = "灯火 · 随行"; UI.Name(this,Title); Width = 380; Height = 460; MinWidth = 340; MinHeight = 360; MaxWidth = MaxHeight = 2400; Background = UI.Background; Foreground = UI.Ink; FontFamily = new FontFamily("Segoe UI, Microsoft YaHei UI, Microsoft YaHei"); FontSize = 14;
            WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.CanResize; ShowActivated = false; UseLayoutRounding = true; SnapsToDevicePixels = true;
            Left = SystemParameters.WorkArea.Right-Width-16; Top = SystemParameters.WorkArea.Top+40;
            frame.RowDefinitions.Add(new RowDefinition { Height = new GridLength(48) }); frame.RowDefinitions.Add(new RowDefinition()); frame.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var chrome = new Grid { Background = UI.Brush("#282E2B") }; chrome.ColumnDefinitions.Add(new ColumnDefinition()); chrome.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var brand = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(16,0,0,0) }; brand.Children.Add(UI.Icon("lamp",22,UI.Brush("#E8C88A"))); var brandText = UI.Text("灯火 · 随行",17,UI.Brush("#F7F3E8")); brandText.FontWeight = FontWeights.SemiBold; brandText.Margin = new Thickness(10,0,0,0); brand.Children.Add(brandText); chrome.Children.Add(brand);
            chrome.MouseLeftButtonDown += delegate(object s,MouseButtonEventArgs e) { if (!Host.Frozen && !UI.InButton(e.OriginalSource as DependencyObject)) { DragMove(); SaveLayout(); } };
            var tools = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0,0,6,0) };
            var reset = UI.Button("",ResetLayout); reset.Content=UI.Icon("reset",17,UI.Brush("#F7F3E8")); UI.Name(reset,"恢复默认大小与位置"); reset.ToolTip = "恢复默认大小与位置 · 保留当前工作";
            var compact = UI.Button("",delegate { Host.Send("collapse"); }); compact.Content = UI.Icon("collapse",17,UI.Brush("#F7F3E8")); UI.Name(compact,"收起灯火助手"); compact.ToolTip = "暂时收起 · 再点灯标展开";
            more = UI.Button("",ShowMore); more.Content = UI.Icon("more",18,UI.Brush("#F7F3E8")); UI.Name(more,"更多操作"); more.ToolTip = "方案、备份、窗口与设置";
            foreach(Button tool in new[]{reset,compact,more}) { tool.Style = (Style)FindResource("ChromeButton"); tool.Padding = new Thickness(7,4,7,4); tool.Margin = new Thickness(0); tool.MinWidth = 32; tools.Children.Add(tool); }
            Grid.SetColumn(tools,1); chrome.Children.Add(tools); frame.Children.Add(chrome);
            workspace.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); workspace.RowDefinitions.Add(new RowDefinition()); Grid.SetRow(workspace,1);
            var tabs = new UniformGrid { Columns = 5, Margin = new Thickness(8,4,8,3) };
            foreach (string[] pair in new[] {new[]{"overview","提示"},new[]{"inventory","背包"},new[]{"alchemy","炼金"},new[]{"floor","本层"},new[]{"lookup","手册"}}) {
                string key = pair[0]; var icon = UI.Icon(key,15); icon.VerticalAlignment = VerticalAlignment.Center; icon.Margin = new Thickness(0,0,5,0); navigationGlyphs.Add(icon); var name = UI.Text(pair[1],12,UI.Muted); name.VerticalAlignment = VerticalAlignment.Center;
                var inside = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center }; inside.Children.Add(icon); inside.Children.Add(name);
                var button = UI.Button("",delegate { OpenPage(key); }); button.Content = inside; button.Padding = new Thickness(2,6,2,6); button.Margin = new Thickness(1,0,1,0); button.Background = Brushes.Transparent; button.ToolTip = pair[1]; UI.Name(button,pair[1]); tabs.Children.Add(button); navigation[key] = button; navigationLabels[key] = name;
            }
            workspace.Children.Add(new Border { BorderBrush = UI.Line, BorderThickness = new Thickness(0,0,0,1), Child = tabs });
            var area = new Grid { Margin = new Thickness(16,8,14,2) }; area.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); area.RowDefinitions.Add(new RowDefinition()); heading.FontWeight = FontWeights.SemiBold; heading.Margin = new Thickness(0,0,0,8); area.Children.Add(heading); Grid.SetRow(content,1); area.Children.Add(content); Grid.SetRow(area,1); workspace.Children.Add(area); frame.Children.Add(workspace);
            var footer = new StackPanel { Margin = new Thickness(16,0,20,3) };
            var stamp = new DockPanel(); DockPanel.SetDock(protection,Dock.Right); protection.Margin=new Thickness(10,0,0,0); stamp.Children.Add(protection); stamp.Children.Add(sourceBrief);
            sourceDetails=UI.Section("存档详情",UI.Stack(source,life,statistics,snapshotNotes,UI.Buttons(UI.Button("刷新",delegate { Host.Send("refresh"); }),UI.Button("存档历史",delegate { OpenPage("backups"); }),UI.Button("角色条件",delegate { OpenPage("character"); }))),false); sourceDetails.Header=stamp; sourceDetails.Margin=new Thickness(0); footer.Children.Add(sourceDetails);
            Status.Margin = new Thickness(0,3,0,0); Status.Visibility = Visibility.Collapsed; footer.Children.Add(Status); footerScroll = UI.Scroll(footer); footerScroll.MaxHeight = 170; Grid.SetRow(footerScroll,2); frame.Children.Add(footerScroll);
            SizeChanged += delegate { foreach(var icon in navigationGlyphs) icon.Visibility = ActualWidth < 430 ? Visibility.Collapsed : Visibility.Visible; };
            var grip = UI.Name(new Thumb { Width = 18, Height = 18, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Bottom, Cursor = Cursors.SizeNWSE, ToolTip = "拖动调整窗口大小" }, "调整窗口大小");
            var gripArea = new FrameworkElementFactory(typeof(Border)); gripArea.SetValue(Border.BackgroundProperty,Brushes.Transparent); var gripVisual = new FrameworkElementFactory(typeof(Path)); gripVisual.SetValue(Path.DataProperty,Geometry.Parse("M 6,16 L 16,6 M 11,16 L 16,11")); gripVisual.SetValue(Path.StrokeProperty,UI.Muted); gripVisual.SetValue(Path.StrokeThicknessProperty,1.0); gripArea.AppendChild(gripVisual); grip.Template = new ControlTemplate(typeof(Thumb)) { VisualTree = gripArea };
            grip.DragDelta += delegate(object sender,DragDeltaEventArgs e) { if (Host.Frozen) return; Width = Math.Max(MinWidth,Math.Min(MaxWidth,Width+e.HorizontalChange)); Height = Math.Max(MinHeight,Math.Min(MaxHeight,Height+e.VerticalChange)); }; grip.DragCompleted += delegate { ClampBounds(); SaveLayout(); }; Grid.SetRow(grip,2); frame.Children.Add(grip);
            summary.Focusable=true; overview.Children.Add(summary);

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
            layoutTimer.Interval = TimeSpan.FromMilliseconds(250); layoutTimer.Tick += delegate { layoutTimer.Stop(); SaveLayout(); }; SizeChanged += delegate { bool small=ActualHeight<480 && !Collapsed; frame.RowDefinitions[0].Height=new GridLength(small ? 40 : 46); heading.Margin=new Thickness(0,0,0,small ? 4 : 8); footerScroll.MaxHeight=Math.Min(220,Math.Max(120,ActualHeight*.45)); QueueLayout(); }; LocationChanged += delegate { QueueLayout(); };
            IsVisibleChanged += delegate { Host.VisibilityAll(); }; Closing += delegate(object s,CancelEventArgs e) { if (!shutdown) { e.Cancel = true; Host.Send("collapse"); } };
            KeyDown += delegate(object s,KeyEventArgs e) { if (e.Key == Key.Escape && !Host.Frozen) { Host.Send("collapse"); e.Handled = true; } };
            PreviewKeyDown += delegate(object s,KeyEventArgs e) { if (e.Key == Key.F1) Host.Send("panel","page","help"); if (e.Key == Key.F && Keyboard.Modifiers == ModifierKeys.Control) { OpenPage("lookup"); Host.Lookup.FocusSearch(); e.Handled = true; } };
            PreviewGotKeyboardFocus+=delegate(object s,KeyboardFocusChangedEventArgs e) { var element=e.NewFocus as DependencyObject; if(element!=null && content.IsAncestorOf(element)) workFocus=e.NewFocus; };
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
            var connection = UI.Stack(UI.Text("以下更改选择后立即应用。下方的保存按钮只保存游戏提示与快捷键。",13,UI.Muted),UI.Field("已应用的存档目录（可选择复制）",saveRoot),UI.Field("存档槽位",slot),top,UI.Field("启动时打开",startup),UI.Buttons(UI.Button("选择并连接存档目录…",delegate { using (var picker = new Forms.FolderBrowserDialog { Description = "选择包含 game1、game2 等文件夹的存档目录", SelectedPath=saveRoot.Text, ShowNewFolderButton = false }) { if (picker.ShowDialog(new NativeOwner(Handle)) == Forms.DialogResult.OK) Host.Send("directory","path",picker.SelectedPath); } }),UI.Button("刷新存档",delegate { Host.Send("refresh"); }),UI.Button("重新读取已应用连接",delegate { Host.Send("reload_connection"); })));
            Host.Settings.Connection = connection; Host.Settings.Prepend(connection); pages[page] = pane;
        } else pages[page] = pane; }
        public void OpenPage(string page) { if (Host.Frozen) return; if (page == "lookup") Host.Send("show_lookup"); else if (page == "settings") Host.Send("show_settings"); else if (page == "plans") Host.Send("choose_plan","surface","lookup"); else if (page != "overview" && page != "floor") Host.Send("game_page","page",page); ShowPage(page); }
        public void ShowPage(string page) {
            if(!pages.ContainsKey(page)) return;
            bool changed=Page!=page; if(Page=="inventory" && page!="inventory") Host.Send("leave_inventory");
            Page=page; content.Content=pages[page];
            var names=new Dictionary<string,string> {{"overview","最近局势"},{"inventory","背包"},{"equipment","装备比较"},{"alchemy","炼金计划"},{"floor","本层"},{"lookup","手册"},{"character","角色条件"},{"map","已探索地图"},{"backups","存档历史"},{"plans","我的方案"},{"settings","设置"}};
            heading.Text=names[page]; heading.Visibility=navigation.ContainsKey(page) ? Visibility.Collapsed : Visibility.Visible;
            string selected=page=="equipment" ? "inventory" : page=="map" ? "floor" : page=="character" ? "overview" : page;
            foreach(var pair in navigation) {
                bool active=pair.Key==selected; pair.Value.Background=active ? UI.Brush("#EEE2CA") : Brushes.Transparent;
                pair.Value.BorderThickness=new Thickness(0,0,0,active ? 2 : 0); pair.Value.BorderBrush=UI.Gold;
                navigationLabels[pair.Key].Foreground=active ? UI.Gold : UI.Muted; navigationLabels[pair.Key].FontWeight=active ? FontWeights.SemiBold : FontWeights.Normal;
                AutomationProperties.SetItemStatus(pair.Value,active ? "当前页面" : "");
            }
            if(changed) UI.Fade(content); Host.VisibilityAll(); if(!changingLayout) SaveLayout();
        }
        void ShowMore() {
            UI.Menu(more,UI.Item("我的方案",delegate { OpenPage("plans"); }),UI.Item("继续编辑草稿…",delegate { Host.Send("list_drafts"); }),
                new Separator(),UI.Item("立即备份已保存进度",delegate { Host.Send("capture"); }),UI.Item("刷新存档",delegate { Host.Send("refresh"); }),UI.Item("存档历史",delegate { OpenPage("backups"); }),
                new Separator(),UI.Item("设置",delegate { OpenPage("settings"); }),UI.Item("恢复默认大小与位置",ResetLayout),UI.Item("完整面板",delegate { Host.Send("panel","page","overview"); }),
                new Separator(),UI.Item("退出灯火",delegate { Host.Send("exit"); }));
        }
        void QueueLayout() { if (!changingLayout && !Host.Frozen) { layoutTimer.Stop(); layoutTimer.Start(); } }
        void ClampBounds() { var scale = SystemDpi/96; var area = Forms.Screen.FromRectangle(new System.Drawing.Rectangle((int)(Left*scale),(int)(Top*scale),(int)(Width*scale),(int)(Height*scale))).WorkingArea; double x=area.Left/scale,y=area.Top/scale,w=area.Width/scale,h=area.Height/scale; Width = Math.Min(Width,w); Height = Math.Min(Height,h); Left = Math.Max(x,Math.Min(Left,x+w-Width)); Top = Math.Max(y,Math.Min(Top,y+h-Height)); }
        public void Collapse() { if (Collapsed) return; changingLayout = true; if (WindowState != WindowState.Normal) WindowState = WindowState.Normal; expandedBounds = new Rect(Left,Top,Width,Height); Collapsed = true; frame.Visibility = Visibility.Collapsed; MinWidth = MinHeight = 0; ResizeMode = ResizeMode.NoResize; Width = 36; Height = 68; handle.Visibility = Visibility.Visible; ClampBounds(); changingLayout = false; SaveLayout(); Host.VisibilityAll(); }
        public void RebindTaskFocus(string page,Dictionary<string,Control> before,Dictionary<string,Control> after,UIElement fallback,IInputElement priorFocus) {
            string key=null; Control nearest=null; var focused=workFocus as DependencyObject; foreach(var item in before) if((Object.ReferenceEquals(workFocus,item.Value) || (focused!=null && item.Value.IsAncestorOf(focused))) && (nearest==null || nearest.IsAncestorOf(item.Value))) { key=item.Key; nearest=item.Value; }
            if(key==null) return;
            bool restore=IsActive && !Collapsed && Page==page && priorFocus==workFocus;
            Control target; bool retained=after.TryGetValue(key,out target) && target.IsEnabled;
            bool same=retained && Object.ReferenceEquals(before[key],target);
            if(!same) { workFocus=retained ? (IInputElement)target : fallback; var section=workFocus as Expander; if(section!=null) { section.ApplyTemplate(); workFocus=section.Template.FindName("title",section) as IInputElement ?? section; } }
            if(same && Keyboard.FocusedElement==workFocus) return;
            var next=workFocus as UIElement;
            if(restore) Dispatcher.BeginInvoke(new Action(delegate { if(IsActive && !Collapsed && Page==page && next!=null && next.IsVisible && next.IsEnabled) next.Focus(); }));
        }
        public void Expand() { if (!Collapsed) return; changingLayout = true; Collapsed = false; handle.Visibility = Visibility.Collapsed; MinWidth = 340; MinHeight = 360; ResizeMode = ResizeMode.CanResize; Left=expandedBounds.X; Top=expandedBounds.Y; Width=expandedBounds.Width; Height=expandedBounds.Height; frame.Visibility = Visibility.Visible; ClampBounds(); changingLayout = false; SaveLayout(); Host.VisibilityAll(); Dispatcher.BeginInvoke(new Action(delegate { var focus=workFocus as UIElement; if(focus!=null && focus.IsVisible && focus.IsEnabled) focus.Focus(); })); }
        public void FlushLayout() { layoutTimer.Stop(); SaveLayout(false,true); }
        public void SaveLayout(bool reset = false,bool exiting = false) { if (changingLayout || Host.Frozen && !exiting) return; LayoutRestored = true; Rect normal = Collapsed ? expandedBounds : new Rect(Left,Top,Width,Height); if (attached) { gameX = (int)Math.Round(Left-gameBounds.Left); gameY = (int)Math.Round(Top-gameBounds.Top); } Host.Send(reset ? "layout_reset" : "window_layout","layout",Data.Map("width",Math.Max(340,(int)Math.Round(normal.Width)),"height",Math.Max(360,(int)Math.Round(normal.Height)),"x",(int)Math.Round(normal.X),"y",(int)Math.Round(normal.Y),"game_x",gameX,"game_y",gameY,"collapsed",Collapsed,"page",Page)); }
        public void ApplyLayout(Dictionary<string,object> d) { changingLayout = true; bool collapsed = Data.Flag(d,"collapsed"); gameX=(int)Data.Number(d,"game_x"); gameY=(int)Data.Number(d,"game_y"); Width=Math.Max(340,Data.Number(d,"width")); Height=Math.Max(360,Data.Number(d,"height")); if (d.ContainsKey("x") && d["x"] != null) { Left=Data.Number(d,"x"); Top=Data.Number(d,"y"); } ClampBounds(); expandedBounds=new Rect(Left,Top,Width,Height); ShowPage(Data.Text(d,"page","overview")); changingLayout=false; if (collapsed) Collapse(); }
        void ResetLayout() { bool collapsed=Collapsed; Expand(); changingLayout=true; Width=380; Height=460; gameX=gameY=16; Left=attached ? gameBounds.Left+16 : SystemParameters.WorkArea.Right-Width-16; Top=attached ? gameBounds.Top+16 : SystemParameters.WorkArea.Top+40; ClampBounds(); expandedBounds=new Rect(Left,Top,Width,Height); changingLayout=false; if (collapsed) Collapse(); SaveLayout(true); }
        public void FollowGame(Dictionary<string,object> d) { var rect=Data.Array(d,"rect"); if (rect.Length==4) { bool first=!attached; double scale=SystemDpi/96; gameBounds=new Rect(Convert.ToDouble(rect[0])/scale,Convert.ToDouble(rect[1])/scale,(Convert.ToDouble(rect[2])-Convert.ToDouble(rect[0]))/scale,(Convert.ToDouble(rect[3])-Convert.ToDouble(rect[1]))/scale); attached=true; changingLayout=true; Left=gameBounds.Left+gameX; Top=gameBounds.Top+gameY; expandedBounds.X=Left; expandedBounds.Y=Top; ClampBounds(); changingLayout=false; Topmost=true; if(first && !LayoutRestored) Collapse(); } else { attached=false; Topmost=top.IsChecked==true; } if(attached) { if(Data.Flag(d,"visible") && !IsVisible) Show(); else if(!Data.Flag(d,"visible") && IsVisible) Hide(); Host.VisibilityAll(); } }
        public void CloseForShutdown() { shutdown=true; layoutTimer.Stop(); Close(); }
        public void Error(string text) { Status.Text=text; Status.Visibility=String.IsNullOrEmpty(text) ? Visibility.Collapsed : Visibility.Visible; }
        string FloorFocusKey(IInputElement focused) {
            var target=focused as DependencyObject; string best="";
            if(target==null) return best;
            foreach(var pair in floorControls) if((Object.ReferenceEquals(pair.Value,target) || pair.Value.IsAncestorOf(target)) && pair.Key.Length>best.Length) best=pair.Key;
            return best;
        }
        UIElement FloorFocusTarget(string key) {
            UIElement target; if(floorControls.TryGetValue(key,out target)) return target;
            int role=key.LastIndexOf('|'); string path=role<0 ? key : key.Substring(0,role);
            while(path.Length>0) { if(floorControls.TryGetValue(path+"|header",out target)) return target; int slash=path.LastIndexOf('/'); path=slash<0 ? "" : path.Substring(0,slash); }
            return floorControls["|map"];
        }
        void FloorNodes(StackPanel parent,object[] nodes,string path) {
            foreach(object raw in nodes) {
                var row=raw as Dictionary<string,object>; if(row==null) continue;
                string id=Data.Text(row,"id", ""), identity=path+"/"+id; var children=Data.Array(row,"children"); var body=new StackPanel();
                string detail=Data.Text(row,"detail",""); if(detail.Length>0) {
                    if(id=="monsters") { bool conditions; floorExpanded.TryGetValue(identity+"/conditions",out conditions); var scope=UI.Section("出现范围与条件",UI.Text(detail,12,UI.Muted),conditions); scope.Expanded+=delegate { floorExpanded[identity+"/conditions"]=true; }; scope.Collapsed+=delegate { floorExpanded[identity+"/conditions"]=false; }; body.Children.Add(scope); floorControls[identity+"/conditions|header"]=scope; }
                    else body.Children.Add(UI.Text(detail,12,UI.Muted));
                }
                if(id=="hidden" && floorReveal!=null) { body.Children.Add(UI.Text("只在助手显示；不改变游戏。",12,UI.Muted)); body.Children.Add(floorReveal); floorControls[identity+"|reveal"]=floorReveal; }
                if(identity.StartsWith("/monsters/") && (id.StartsWith("actors.mobs.") || id.StartsWith("levels.") || id.StartsWith("items.quest."))) {
                    var button=UI.Button("查看数值",delegate { Host.Send("floor_reference","id",id,"token",floorToken); }); body.Children.Add(button); floorControls[identity+"|reference"]=button;
                }
                if(identity.StartsWith("/hidden/") && id.StartsWith("item-floor-")) {
                    var button=UI.Button("查看物品数值",delegate { Host.Send("floor_item_reference","id",id,"token",floorToken); }); body.Children.Add(button); floorControls[identity+"|reference"]=button;
                }
                FloorNodes(body,children,identity);
                if(body.Children.Count>0) {
                    bool expanded; if(!floorExpanded.TryGetValue(identity,out expanded)) expanded=Data.Flag(row,"expanded");
                    var section=UI.Section(Data.Text(row,"text",""),body,expanded); floorControls[identity+"|header"]=section;
                    if(Data.Object(row,"artwork").Count>0) section.Header=UI.ImageRow(Data.Text(row,"text",""),Data.Object(row,"artwork"));
                    section.Expanded+=delegate { floorExpanded[identity]=true; }; section.Collapsed+=delegate { floorExpanded[identity]=false; }; parent.Children.Add(section);
                } else { var text=UI.Text(Data.Text(row,"text","")); text.Margin=new Thickness(0,0,0,8); parent.Children.Add(text); }
            }
        }
        void RenderFloor(Dictionary<string,object> guide) {
            floorToken=Data.Text(guide,"token","");
            var presentation=new Dictionary<string,object>(guide); presentation.Remove("token");
            string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(presentation);
            if(signature==floorSignature) return;
            string owner=Data.Text(guide,"owner",""); bool sameOwner=owner==floorOwner;
            var oldFocus=Keyboard.FocusedElement; bool focused=floorBody.IsKeyboardFocusWithin;
            string key=FloorFocusKey(focused ? oldFocus : workFocus);
            var scroll=pages["floor"] as ScrollViewer; double position=sameOwner ? scroll.VerticalOffset : 0;
            if(!sameOwner) floorExpanded.Clear();
            floorBody.Children.Clear(); floorControls.Clear();
            floorBody.Children.Add(UI.Text(Data.Text(guide,"caption","当前楼层"),12,UI.Muted));
            string warning=Data.Text(guide,"warning",""); if(warning.Length>0) floorBody.Children.Add(UI.Text(warning,12,UI.Gold));
            floorReveal=UI.Button(Data.Flag(guide,"revealed") ? "收起隐藏内容" : "主动揭示隐藏内容",delegate { Host.Send("reveal_floor","token",floorToken); }); floorReveal.IsEnabled=Data.Flag(guide,"enabled");
            var map=UI.Button("查看已探索地图",delegate { OpenPage("map"); }); floorBody.Children.Add(map); floorControls["|map"]=map;
            FloorNodes(floorBody,Data.Array(guide,"nodes"),""); floorSignature=signature; floorOwner=owner;
            UIElement target=FloorFocusTarget(sameOwner ? key : "");
            if(key.Length>0) workFocus=target;
            Dispatcher.BeginInvoke(new Action(delegate {
                if(floorSignature!=signature) return;
                if(focused && IsActive && Page=="floor" && !Collapsed && (Object.ReferenceEquals(Keyboard.FocusedElement,oldFocus) || Keyboard.FocusedElement==null || Object.ReferenceEquals(Keyboard.FocusedElement,this))) target.Focus();
                scroll.ScrollToVerticalOffset(position);
            }));
        }
        FrameworkElement Insight(Dictionary<string,object> row) {
            string id=Data.Text(row,"id",""), title=Data.Text(row,"title",""), detail=Data.Text(row,"body","");
            var body=UI.Stack(UI.Text(detail,13)); string basis=Data.Text(row,"basis",""); if(basis.Length>0) body.Children.Add(UI.Text(basis,12,UI.Muted));
            var actions=new WrapPanel(); foreach(object raw in Data.Array(row,"actions")) {
                var action=raw as Dictionary<string,object>; if(action==null) continue;
                int index=(int)Data.Number(action,"index"); if(index<0 || index>=overviewTokens.Length) continue;
                string label=Data.Text(action,"text","查看数值"); var button=UI.Button(label,delegate { if(index<overviewTokens.Length) Host.Send("reference","index",index,"token",Convert.ToString(overviewTokens[index])); });
                actions.Children.Add(button); insightControls[id+"/"+label]=button;
            }
            if(actions.Children.Count>0) { actions.Margin=new Thickness(0,8,0,0); body.Children.Add(actions); }
            bool expanded; insightExpanded.TryGetValue(id,out expanded); var section=UI.Section(title,body,expanded); section.Margin=new Thickness(0,0,0,3);
            var labelText=UI.Text(title,14,Data.Text(row,"severity","")=="critical" ? UI.Gold : UI.Ink); labelText.FontWeight=FontWeights.SemiBold;
            var header=UI.Stack(labelText); string brief=Data.Text(row,"summary",""), assumption=Data.Text(row,"assumption","");
            if(brief.Length>0) { var value=UI.Text(brief,14); value.Margin=new Thickness(0,4,0,0); header.Children.Add(value); }
            if(assumption.Length>0) header.Children.Add(UI.Text(assumption,12,UI.Muted));
            section.Header=header; section.Expanded+=delegate { insightExpanded[id]=true; }; section.Collapsed+=delegate { insightExpanded[id]=false; }; insightControls[id]=section;
            return section;
        }
        void RenderOverview(Dictionary<string,object> data) {
            bool empty=Data.Flag(data,"no_data"); overviewTokens=Data.Array(data,"reference_tokens");
            var insights=Data.Array(data,"insights"); var secondary=Data.Array(data,"secondary_advice"); string readError=Data.Text(data,"read_error","");
            string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(Data.Map("insights",insights,"secondary",secondary,"no_data",empty,"read_error",readError,"waiting",Data.Flag(data,"waiting_for_save"),"references",Data.Array(data,"references")));
            if(signature==overviewText) return; overviewText=signature;
            string focusKey=""; var focused=workFocus as DependencyObject;
            foreach(var pair in insightControls) if(pair.Value==focused) { focusKey=pair.Key; break; }
            if(focusKey.Length==0 && focused!=null) foreach(var pair in insightControls) if(pair.Value.IsAncestorOf(focused)) { focusKey=pair.Key; break; }
            bool hadOverviewFocus=focusKey.Length>0 || focused!=null && (Object.ReferenceEquals(focused,summary) || summary.IsAncestorOf(focused));
            bool restore=hadOverviewFocus && IsActive && !Collapsed && Page=="overview" && Keyboard.FocusedElement==workFocus;
            summary.Children.Clear(); insightControls.Clear();
            if(empty || readError.Length>0) {
                bool waiting=empty && readError.Length==0;
                var guide=UI.Stack(UI.Text(waiting ? "保存一局后，显示相关提示" : "读取受阻，提示已暂停",14));
                if(!waiting) guide.Children.Add(UI.Section("读取原因",UI.Text(readError,13),false));
                guide.Children.Add(UI.Buttons(UI.Button(waiting ? "查手册" : "检查连接",delegate { if(waiting) OpenPage("lookup"); else { OpenPage("settings"); Host.Settings.OpenConnection(); } },true),UI.Button(waiting ? "检查连接" : "重试",delegate { if(waiting) { OpenPage("settings"); Host.Settings.OpenConnection(); } else Host.Send("refresh"); })));
                summary.Children.Add(guide);
            }
            var extra=new StackPanel(); int count=0;
            foreach(object raw in insights) { var row=(Dictionary<string,object>)raw; var target=count++<3 ? summary : extra; target.Children.Add(Insight(row)); }
            if(!empty && readError.Length==0 && insights.Length==0) {
                summary.Children.Add(UI.Text("暂无需要展开的提示",14,UI.Muted));
                summary.Children.Add(UI.Buttons(UI.Button("比较装备",delegate { OpenPage("equipment"); }),UI.Button("查数值",delegate { OpenPage("lookup"); })));
            }
            foreach(object raw in secondary) extra.Children.Add(Insight((Dictionary<string,object>)raw));
            if(extra.Children.Count>0) { var section=UI.Section("其他提示 · "+extra.Children.Count,extra,overviewDetailsExpanded); section.Expanded+=delegate { overviewDetailsExpanded=true; }; section.Collapsed+=delegate { overviewDetailsExpanded=false; }; summary.Children.Add(section); insightControls["__other"]=section; }
            var used=new HashSet<int>(); foreach(object raw in insights) foreach(object action in Data.Array((Dictionary<string,object>)raw,"actions")) used.Add((int)Data.Number((Dictionary<string,object>)action,"index")); foreach(object raw in secondary) foreach(object action in Data.Array((Dictionary<string,object>)raw,"actions")) used.Add((int)Data.Number((Dictionary<string,object>)action,"index"));
            var references=new StackPanel(); int index=0; foreach(object raw in Data.Array(data,"references")) { int selected=index++; if(used.Contains(selected)) continue; var button=UI.Button(Convert.ToString(raw),delegate { if(selected<overviewTokens.Length) Host.Send("reference","index",selected,"token",Convert.ToString(overviewTokens[selected])); }); button.HorizontalContentAlignment=HorizontalAlignment.Left; references.Children.Add(button); }
            if(references.Children.Count>0) { bool opened; insightExpanded.TryGetValue("__references",out opened); var section=UI.Section("资源资料 · "+references.Children.Count,references,opened); section.Expanded+=delegate { insightExpanded["__references"]=true; }; section.Collapsed+=delegate { insightExpanded["__references"]=false; }; summary.Children.Add(section); insightControls["__references"]=section; }
            UIElement targetFocus; if(!insightControls.TryGetValue(focusKey,out targetFocus)) targetFocus=summary;
            if(hadOverviewFocus) { workFocus=targetFocus; if(restore) Dispatcher.BeginInvoke(new Action(delegate { if(IsActive && !Collapsed && Page=="overview" && targetFocus.IsVisible) targetFocus.Focus(); })); }
        }
        public void Render(Dictionary<string,object> d) { rendering=true; try { life.Text=Data.Text(d,"life",""); statistics.Text=Data.Text(d,"statistics",""); snapshotNotes.Text=Data.Text(d,"snapshot_notes",""); source.Text=Data.Text(d,"source","等待游戏保存"); sourceBrief.Text=Data.Text(d,"source_brief",source.Text); sourceBrief.Foreground=Data.Flag(d,"source_warning") ? UI.Gold : UI.Muted; UI.Name(sourceDetails,"存档详情 · "+sourceBrief.Text); protection.Text=Data.Text(d,"protection","等待备份"); Error(Data.Text(d,"error","")); RenderOverview(d); UI.Replace(saveRoot,Data.Text(d,"save_root","")); startup.SelectedIndex=Data.Text(d,"startup_surface","native")=="native" ? 0 : 1; slot.SelectedIndex=(int)Math.Max(0,Math.Min(6,Data.Number(d,"slot"))); top.IsChecked=Data.Flag(d,"topmost"); if(!attached) Topmost=top.IsChecked==true; if(Host.Settings!=null && Host.Settings.Connection!=null) Host.Settings.Connection.IsEnabled=!Data.Flag(d,"io_busy");
            RenderFloor(Data.Object(d,"floor_guide"));
        } finally { rendering=false; } }
    }
    sealed class NativeOwner : Forms.IWin32Window { readonly IntPtr hwnd; public NativeOwner(IntPtr value) { hwnd=value; } public IntPtr Handle { get { return hwnd; } } }
}
