using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Web.Script.Serialization;

namespace Denghuo.Native {
    // Raw text is never parsed by the presentation; hidden fields survive structural edits.
    sealed class FieldEditor : StackPanel {
        readonly Dictionary<string,FrameworkElement> controls = new Dictionary<string,FrameworkElement>();
        readonly Dictionary<string,TextBlock> hints = new Dictionary<string,TextBlock>();
        readonly Dictionary<string,bool> expanded = new Dictionary<string,bool>();
        Dictionary<string,object> values = new Dictionary<string,object>();
        string signature = "";
        bool rendering;
        public Action<string,bool> Changed;
        public Action Submit;
        public void SetMetadata(string name,string note) { rendering=true; try { values["name"]=name; values["note"]=note; foreach(string key in new[]{"name","note"}) { FrameworkElement control; if(controls.TryGetValue(key,out control) && control is TextBox) UI.Replace((TextBox)control,key=="name" ? name : note); } } finally { rendering=false; } }
        public Dictionary<string,object> Raw() { var raw=new Dictionary<string,object>(values); foreach(var pair in controls) { var text=pair.Value as TextBox; var combo=pair.Value as ComboBox; var multi=pair.Value as StackPanel; if(text!=null) raw[pair.Key]=text.Text; else if(combo!=null) { var choice=combo.SelectedItem as Choice; raw[pair.Key]=choice==null ? "" : choice.Id; } else if(multi!=null) { var selected=new List<string>(); foreach(CheckBox check in multi.Children) if(check.IsChecked==true) selected.Add((string)check.Tag); raw[pair.Key]=String.Join("|",selected.ToArray()); } } return raw; }
        void Edited(string key,bool structural) { if(rendering) return; values=Raw(); if(Changed!=null) Changed(key,structural); }
        public void Render(object[] fields,Dictionary<string,object> raw,bool numeric=false) {
            rendering=true; try { values=new Dictionary<string,object>(raw); var shape=new List<string>(); var serializer=new JavaScriptSerializer(); foreach(object item in fields) { var spec=(Dictionary<string,object>)item; shape.Add(Data.Text(spec,"key","")+Data.Text(spec,"label","")+Data.Text(spec,"section","")+serializer.Serialize(Data.Array(spec,"choices"))); string key=Data.Text(spec,"key",""); if(!values.ContainsKey(key)) values[key]=Data.Text(spec,"raw",""); }
                string next=String.Join("\n",shape.ToArray()); string focused=null; int caret=0; foreach(var pair in controls) if(pair.Value.IsKeyboardFocusWithin) { focused=pair.Key; var edit=pair.Value as TextBox; if(edit!=null) caret=edit.CaretIndex; }
                bool rebuild=next!=signature;
                if(rebuild) { Children.Clear(); controls.Clear(); hints.Clear(); string previous=""; StackPanel group=this; foreach(object item in fields) { var spec=(Dictionary<string,object>)item; string key=Data.Text(spec,"key",""), label=Data.Text(spec,"label",key), section=Data.Text(spec,"section",""); if(section!=previous) { previous=section; group=new StackPanel(); bool open; if(!expanded.TryGetValue(section,out open)) open=section=="选择比较对象" || section=="共同条件" || section=="共享预算" || section.StartsWith("产出目标 1 ") || fields.Length<12; var expander=UI.Section(section,group,open); string identity=section; expander.Expanded+=delegate { expanded[identity]=true; }; expander.Collapsed+=delegate { expanded[identity]=false; }; Children.Add(expander); }
                    FrameworkElement control; object[] choices=Data.Array(spec,"choices"); if(numeric && key=="corrosion_public") { choices=new object[]{Data.Map("id","1","text","游戏显示值（给范围）"),Data.Map("id","0","text","手填精确假设")}; label="酸蚀计算依据"; }
                    if(Data.Flag(spec,"multiple")) { var multi=new StackPanel(); foreach(object choice in choices) { var option=(Dictionary<string,object>)choice; string id=Data.Text(option,"id",""); if(id.Length==0) continue; var check=UI.Name(new CheckBox { Content=UI.Text(Data.Text(option,"text","")),Tag=id },label+" · "+Data.Text(option,"text","")); check.Checked+=delegate { Edited(key,false); }; check.Unchecked+=delegate { Edited(key,false); }; multi.Children.Add(check); } control=multi; }
                    else if(choices.Length>0) { var combo=UI.Combo(label); foreach(object choice in choices) { var option=(Dictionary<string,object>)choice; combo.Items.Add(new Choice(Data.Text(option,"id",""),Data.Text(option,"text",""))); } combo.SelectionChanged+=delegate { Edited(key,!numeric); }; control=combo; }
                    else { var text=UI.Edit(label,numeric ? 80 : 1200); text.TextChanged+=delegate { Edited(key,false); }; if(numeric) text.KeyDown+=delegate(object sender,KeyEventArgs e) { if(e.Key==Key.Enter && Submit!=null) { Submit(); e.Handled=true; } }; control=text; }
                    controls[key]=control; var title=UI.Text(label,12,UI.Muted); title.Margin=new Thickness(0,0,0,6); var hint=UI.Text("",11,UI.Muted); hint.Margin=new Thickness(0,4,0,0); hints[key]=hint; var field=UI.Stack(title,control,hint); field.Margin=new Thickness(0,0,0,14); group.Children.Add(field);
                } signature=next; }
                foreach(object item in fields) { var spec=(Dictionary<string,object>)item; string key=Data.Text(spec,"key",""), value=Data.Text(values,key,Data.Text(spec,"raw","")); var control=controls[key]; var text=control as TextBox; var combo=control as ComboBox; var multi=control as StackPanel;
                    if(text!=null) UI.Replace(text,value); else if(combo!=null) { int found=-1; for(int i=0;i<combo.Items.Count;i++) if(((Choice)combo.Items[i]).Id==value) found=i; if(found<0) found=combo.Items.Add(new Choice(value,"需核对的原始输入："+value)); combo.SelectedIndex=found; }
                    else if(multi!=null) { var selected=new HashSet<string>(value.Split('|')); foreach(string id in selected) { bool found=id.Length==0; foreach(CheckBox check in multi.Children) if((string)check.Tag==id) found=true; if(!found) { var check=UI.Name(new CheckBox { Content=UI.Text("需核对的原始实例："+id),Tag=id },"需核对的原始实例："+id); check.Checked+=delegate { Edited(key,false); }; check.Unchecked+=delegate { Edited(key,false); }; multi.Children.Add(check); } } foreach(CheckBox check in multi.Children) check.IsChecked=selected.Contains((string)check.Tag); }
                    string help=numeric ? Data.Text(spec,"origin","")+(key=="corrosion_public" ? " · 游戏显示值给范围；精确值仅为手填假设" : " · "+Data.Text(spec,"min","")+"–"+Data.Text(spec,"max","")) : Data.Text(spec,"help",""); hints[key].Text=help; hints[key].Visibility=help.Length>0 ? Visibility.Visible : Visibility.Collapsed; System.Windows.Automation.AutomationProperties.SetHelpText(control,help);
                }
                if(rebuild && focused!=null && controls.ContainsKey(focused)) { controls[focused].Focus(); var text=controls[focused] as TextBox; if(text!=null) text.CaretIndex=Math.Min(caret,text.Text.Length); }
            } finally { rendering=false; }
        }
    }

    sealed class SavedMap : FrameworkElement {
        Dictionary<string,object> data=new Dictionary<string,object>();
        static readonly HashSet<int> Obstacles=new HashSet<int>(new[]{0,4,12,13,23,25,26,27,28,33,34,35,36,39});
        static readonly HashSet<int> Stairs=new HashSet<int>(new[]{7,8,21,22,37});
        public SavedMap() { Height=230; Margin=new Thickness(0,12,0,16); UI.Name(this,"保存地图 · 未探索区域保持遮住，地形与坐标可在下方展开"); }
        public void Render(Dictionary<string,object> value) { data=value; Visibility=Data.Array(value,"tiles").Length>0 ? Visibility.Visible : Visibility.Collapsed; InvalidateVisual(); }
        static string ImportantTerrain(int tile) {
            if(tile<0) return "";
            if(tile==0) return "深渊";
            if(tile==17 || tile==18) return tile==17 ? "已主动揭示的隐藏陷阱" : "已发现陷阱";
            if(tile==19) return "失效陷阱";
            if(tile==29) return "水地";
            if(tile==13) return "路障";
            if(tile==12) return "装饰墙";
            if(tile==28) return "炼金台（不可通行）";
            if(tile==24) return "水井";
            if(tile==16) return "已主动揭示的隐藏门";
            if(Stairs.Contains(tile)) return tile==7 ? "上行楼梯" : tile==8 ? "下行楼梯" : tile==21 ? "锁住的出口" : tile==22 ? "解锁的出口" : "特殊入口";
            if(tile>39) return "未识别地形 "+tile;
            return "";
        }
        public string Description() {
            int width=(int)Data.Number(data,"width"); if(width<1) return "";
            var groups=new Dictionary<string,List<string>>(); var tiles=Data.Array(data,"tiles");
            for(int i=0;i<tiles.Length;i++) {
                string name=ImportantTerrain(Convert.ToInt32(tiles[i])); if(name.Length==0) continue;
                if(!groups.ContainsKey(name)) groups[name]=new List<string>();
                groups[name].Add("("+(i%width+1)+", "+(i/width+1)+")");
            }
            var lines=new List<string>();
            if(data.ContainsKey("hero") && data["hero"]!=null) { int hero=Convert.ToInt32(data["hero"]); lines.Add("角色：("+(hero%width+1)+", "+(hero/width+1)+")"); }
            foreach(var pair in groups) lines.Add(pair.Key+" · "+pair.Value.Count+"处："+String.Join("、",pair.Value.ToArray()));
            lines.Add("坐标为（列，行），从1计；未探索区域不列出。未识别编号不代表可以通行。");
            return String.Join("\n",lines.ToArray());
        }
        protected override void OnRender(DrawingContext context) {
            int width=(int)Data.Number(data,"width"), height=(int)Data.Number(data,"height"); var tiles=Data.Array(data,"tiles");
            if(width<1 || height<1 || tiles.Length!=width*height) return;
            double size=Math.Min(ActualWidth/width,ActualHeight/height), left=(ActualWidth-width*size)/2, top=(ActualHeight-height*size)/2;
            var symbol=new Pen(UI.Brush("#29312C"),Math.Max(.7,size/10));
            for(int i=0;i<tiles.Length;i++) {
                int tile=Convert.ToInt32(tiles[i]); double x=left+(i%width)*size,y=top+(i/width)*size;
                Brush brush=tile<0 ? UI.Background : tile>39 ? UI.Brush("#9175A1") :
                    tile==17 || tile==18 ? UI.Brush("#B66F55") : tile==19 ? UI.Brush("#8C8170") :
                    tile==29 || tile==24 ? UI.Brush("#537C86") : Stairs.Contains(tile) ? UI.Brush("#74998A") :
                    Obstacles.Contains(tile) ? UI.Brush("#555E53") : tile==5 || tile==6 || tile==16 || tile==10 || tile==31 || tile==38 ? UI.Brush("#A18760") :
                    tile==2 || tile==3 || tile==15 || tile==30 ? UI.Brush("#788E69") : UI.Brush("#B8BAAC");
                context.DrawRectangle(brush,null,new Rect(x,y,Math.Max(1,size-.65),Math.Max(1,size-.65)));
                if(tile==17 || tile==18 || tile>39) {
                    context.DrawLine(symbol,new Point(x+size*.25,y+size*.25),new Point(x+size*.7,y+size*.7));
                    context.DrawLine(symbol,new Point(x+size*.7,y+size*.25),new Point(x+size*.25,y+size*.7));
                } else if(tile==19) context.DrawRectangle(null,symbol,new Rect(x+size*.25,y+size*.25,size*.45,size*.45));
                else if(tile==24) context.DrawEllipse(null,symbol,new Point(x+size*.5,y+size*.5),size*.25,size*.25);
                else if(tile==29) context.DrawLine(symbol,new Point(x+size*.15,y+size*.55),new Point(x+size*.75,y+size*.55));
                else if(tile==13) context.DrawLine(new Pen(UI.Panel,Math.Max(.7,size/10)),new Point(x+size*.2,y+size*.8),new Point(x+size*.8,y+size*.2));
                if(data.ContainsKey("hero") && data["hero"]!=null && Convert.ToInt32(data["hero"])==i)
                    context.DrawRectangle(UI.Gold,new Pen(UI.Panel,Math.Max(.7,size/10)),new Rect(x+size*.12,y+size*.12,size*.7,size*.7));
            }
        }
    }

    sealed class TaskPane : Grid {
        readonly Helper host; readonly string page;
        readonly FieldEditor fields=new FieldEditor();
        readonly StackPanel output=new StackPanel(), article=new StackPanel(), selector=new StackPanel();
        readonly StackPanel comparison=new StackPanel(), resultDetails=new StackPanel();
        readonly TextBlock mapLegend=UI.Text("金色：角色 · 绿色：楼梯 · 纸色：未探索\n棕色×：陷阱 · 蓝色横线：水地 · 深灰：障碍\n蓝色圆圈：水井 · 空框：失效陷阱 · 紫色×：未识别地形",12,UI.Muted);
        readonly TextBlock mapCoordinates=UI.Text("",12,UI.Muted);
        readonly Expander mapDetails;
        readonly SavedMap map=new SavedMap();
        readonly ScrollViewer scroll;
        readonly WrapPanel actions=new WrapPanel();
        readonly TextBlock notice=UI.Text("",12,UI.Gold);
        readonly TextBlock origin=UI.Text("",12,UI.Muted);
        readonly Button mode;
        readonly Expander selection;
        readonly Expander details;
        readonly Dictionary<string,double> positions=new Dictionary<string,double>();
        readonly Dictionary<string,bool> resultDetailExpanded=new Dictionary<string,bool>();
        readonly Dictionary<string,Control> actionControls=new Dictionary<string,Control>();
        bool rendering,editing,calculated;
        long revision;
        string articleText="", rowSignature="";
        Dictionary<string,object> values=new Dictionary<string,object>();
        public bool Dirty;
        public TaskPane(Helper owner,string name) {
            host=owner; page=name; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            mode=UI.Button("编辑条件",delegate { SetEditing(!editing); }); mode.HorizontalAlignment=HorizontalAlignment.Left; mode.Background=Brushes.Transparent; var taskHeader=new WrapPanel(); taskHeader.Children.Add(mode); if(page=="inventory") taskHeader.Children.Add(UI.Button("装备比较 ›",delegate { host.Manager.OpenPage("equipment"); })); Children.Add(UI.Stack(origin,taskHeader));
            selection=UI.Section(page=="inventory" ? "选择背包物品" : page=="map" ? "选择保存楼层" : "选择存档记录",selector,true); output.Children.Add(selection); output.Children.Add(map); output.Children.Add(mapLegend); mapDetails=UI.Section("地形与坐标（只读）",mapCoordinates,false); output.Children.Add(mapDetails); if(page=="equipment") { output.Children.Add(comparison); details=UI.Section("完整数值与条件",article,true); output.Children.Add(details); } else output.Children.Add(article); output.Children.Add(resultDetails); scroll=UI.Scroll(output); Grid.SetRow(scroll,1); Children.Add(scroll); actions.Margin=new Thickness(0,10,0,0); var bottom=UI.Stack(notice,actions); Grid.SetRow(bottom,2); Children.Add(bottom);
            fields.Changed=delegate(string key,bool structural) { if(rendering || host.Frozen) return; ++revision; Dirty=true; notice.Text=key=="name" || key=="note" ? "备注或名称已修改，尚未保存" : "条件已修改，待重新计算"; notice.Visibility=Visibility.Visible; values=fields.Raw(); host.Send("game_edit","page",page,"values",values,"draft_revision",revision,"structure",structural); if(key!="name" && key!="note") { calculated=false; foreach(string command in new[]{"save","update"}) if(actionControls.ContainsKey(command)) { actionControls[command].IsEnabled=false; actionControls[command].ToolTip="先重新计算有效结果"; } if(editing) { mode.Content="返回说明"; UI.Name(mode,"返回说明"); } articleText="条件已修改，请重新计算。原始输入已保留。"; UI.Article(article,articleText); comparison.Children.Clear(); resultDetails.Children.Clear(); if(details!=null) details.IsExpanded=true; } };
        }
        public void SetPlanMetadata(string name,string note) { fields.SetMetadata(name,note); values=fields.Raw(); Dirty=true; ++revision; Flush(); }
        public Dictionary<string,object> Raw() { return fields.Raw(); }
        public void Flush() { host.Send("game_edit","page",page,"values",Raw(),"draft_revision",revision); }
        void SetEditing(bool value) { positions[editing ? "edit" : "result"]=scroll.VerticalOffset; editing=value; mode.Content=editing ? calculated ? "查看结果" : "返回说明" : "调整条件"; UI.Name(mode,Convert.ToString(mode.Content)); scroll.Content=editing ? (object)fields : output; double position; scroll.ScrollToVerticalOffset(positions.TryGetValue(editing ? "edit" : "result",out position) ? position : 0); UI.Fade(scroll); }
        void RenderComparison(Dictionary<string,object> data) {
            comparison.Children.Clear(); var choices=Data.Array(data,"choices"); details.IsExpanded=choices.Length!=2; if(choices.Length!=2) return;
            foreach(object item in choices) { var choice=(Dictionary<string,object>)item; string side=comparison.Children.Count==0 ? "A" : "B"; comparison.Children.Add(UI.Card(UI.ImageRow(side+" · "+Data.Text(choice,"name",""),Data.Object(choice,"artwork"),true))); }
            var planning=Data.Object(data,"planning"); if(planning.Count>0) { var pending=new List<string>(); int n=0; foreach(object item in Data.Array(planning,"choices")) { var side=(Dictionary<string,object>)item; string label=n++==0 ? "A" : "B"; if(Data.Flag(side,"upgrade_pending")) pending.Add(label); } if(pending.Count>0) { var notice=UI.Text("预算待确认 · "+String.Join("、",pending.ToArray())+" 注魔假设未确认",13,UI.Gold); notice.Margin=new Thickness(0,12,0,8); comparison.Children.Add(notice); } comparison.Children.Add(UI.Text("预算 "+Data.Text(planning,"upgrade_budget","0")+" 卷 / "+Data.Text(planning,"strength_budget","0")+" 瓶力量药剂；A、B分别使用同一预算，不能同时花费。",12,UI.Muted)); n=0; foreach(object item in Data.Array(planning,"choices")) { var side=(Dictionary<string,object>)item; comparison.Children.Add(UI.Text((n++==0 ? "A" : "B")+" · 投入 "+Data.Text(side,"spent_upgrades","?")+" 卷，余 "+Data.Text(side,"remaining_upgrades","?")+" 卷",12)); } }
            comparison.Children.Add(UI.Text("当前 → 升级一次",11,UI.Muted)); var grid=new Grid { Margin=new Thickness(0,12,0,14) }; grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1.2,GridUnitType.Star) }); grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition()); int row=0; foreach(object item in Data.Array(data,"rows")) { var metric=(Dictionary<string,object>)item; var cells=Data.Array(metric,"values"); if(cells.Length!=4) continue; grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); var label=UI.Text(Data.Text(metric,"label",""),12,UI.Muted); label.Margin=new Thickness(0,7,6,7); Grid.SetRow(label,row); grid.Children.Add(label); for(int i=0;i<2;i++) { var value=UI.Text((i==0 ? "A " : "B ")+Convert.ToString(cells[i*2])+" → "+Convert.ToString(cells[i*2+1]),12); value.Margin=new Thickness(0,7,5,7); Grid.SetRow(value,row); Grid.SetColumn(value,i+1); value.ToolTip=Data.Text(metric,"condition",""); grid.Children.Add(value); } row++; } comparison.Children.Add(grid); comparison.Children.Add(UI.Text(Data.Text(data,"notice",""),11,UI.Muted));
        }
        public void Render(Dictionary<string,object> d) {
            if(Data.Number(d,"draft_revision")<revision) return; rendering=true; try { revision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty"); calculated=Data.Flag(d,"calculated"); values=new Dictionary<string,object>(Data.Object(d,"raw"));
                var taskSource=Data.Object(d,"task_source"); origin.Text=Data.Text(taskSource,"brief","");
                origin.Foreground=Data.Flag(taskSource,"stale") ? UI.Gold : UI.Muted;
                origin.ToolTip=Data.Text(taskSource,"detail",""); origin.Visibility=origin.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                UI.Name(origin,"任务条件来源 · "+origin.Text); object[] specs=Data.Array(d,"fields"); bool first=fields.Children.Count==0; fields.Render(specs,values); mode.Visibility=specs.Length>0 ? Visibility.Visible : Visibility.Collapsed; if(first && specs.Length>0) SetEditing(true); mode.Content=editing ? calculated ? "查看结果" : "返回说明" : "调整条件"; UI.Name(mode,Convert.ToString(mode.Content));
                string text=Data.Text(d,"text",""); if(text!=articleText) { articleText=text; UI.IllustratedArticle(article,text,Data.Object(d,"artwork")); if(page=="equipment") RenderComparison(Data.Object(d,"comparison")); }
                resultDetails.Children.Clear(); foreach(object raw in Data.Array(d,"result_details")) { var extra=raw as Dictionary<string,object>; if(extra==null) continue; var body=new StackPanel(); UI.Article(body,Data.Text(extra,"text","")); string identity=Data.Text(extra,"id",""); bool expanded; if(!resultDetailExpanded.TryGetValue(identity,out expanded)) expanded=Data.Flag(extra,"expanded"); var section=UI.Section(Data.Text(extra,"title","详细记录"),body,expanded); section.Expanded+=delegate { resultDetailExpanded[identity]=true; }; section.Collapsed+=delegate { resultDetailExpanded[identity]=false; }; resultDetails.Children.Add(section); }
                map.Render(Data.Object(d,"map")); mapLegend.Visibility=mapDetails.Visibility=map.Visibility; mapCoordinates.Text=map.Description(); var rows=Data.Array(d,"rows"); string next=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(rows)+Data.Text(d,"selected",""); if(next!=rowSignature) { selector.Children.Clear(); foreach(object item in rows) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""), token=Data.Text(row,"token",""); var button=UI.Button("",delegate { if(!host.Frozen) { host.Send("game_select","page",page,"id",id,"token",token); selection.IsExpanded=false; } }); string caption=Data.Text(row,"summary",Data.Text(row,"text","")); button.Content=UI.ImageRow(caption,Data.Object(row,"artwork")); UI.Name(button,caption); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; button.Margin=new Thickness(0,0,0,5); if(id==Data.Text(d,"selected","")) button.BorderThickness=new Thickness(1); selector.Children.Add(button); } rowSignature=next; } selection.Visibility=rows.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                notice.Text=Data.Text(d,"notice",""); notice.Visibility=notice.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                actions.Children.Clear(); actionControls.Clear(); var extras=new List<MenuItem>(); Button more=null;
                string primaryCommand=page=="inventory" ? "reference" : page=="backups" ? "backup_preview" : page=="map" ? "map_known" : "calculate";
                if(page=="backups") foreach(object item in Data.Array(d,"actions")) if(Data.Text((Dictionary<string,object>)item,"id","")=="backup_confirm") primaryCommand="backup_confirm";
                foreach(object item in Data.Array(d,"actions")) {
                    var action=(Dictionary<string,object>)item; string command=Data.Text(action,"id","");
                    Action clicked=delegate { if(host.Frozen) return; Flush(); host.Send("game_action","page",page,"command",command=="save" ? "name_plan" : command,"values",Raw(),"draft_revision",revision); };
                    string label=Data.Text(action,"text",""), reason=Data.Text(action,"reason",""); bool disabled=Data.Flag(action,"disabled");
                    if(command==primaryCommand) { var button=UI.Button(label,clicked,true); button.IsEnabled=!disabled; if(reason.Length>0) { button.ToolTip=reason; System.Windows.Controls.ToolTipService.SetShowOnDisabled(button,true); System.Windows.Automation.AutomationProperties.SetHelpText(button,reason); } actions.Children.Add(button); actionControls[command]=button; }
                    else if(!(page=="inventory" && Data.Text(d,"selected","").Length==0)) { var menuItem=UI.Item(label,clicked,!disabled); if(reason.Length>0) { menuItem.ToolTip=reason; System.Windows.Controls.ToolTipService.SetShowOnDisabled(menuItem,true); System.Windows.Automation.AutomationProperties.SetHelpText(menuItem,reason); } extras.Add(menuItem); actionControls[command]=menuItem; }
                }
                if(extras.Count>0) { more=UI.Button("更多操作",delegate { UI.Menu(more,extras.ToArray()); }); actions.Children.Add(more); }
                if(Data.Flag(d,"focus_result")) { SetEditing(false); scroll.ScrollToTop(); }
            } finally { rendering=false; }
        }
    }

    sealed class LookupForm : Grid {
        readonly Helper Host;
        readonly TextBox search=UI.Edit("搜索物品、敌人或技能",200), note=UI.Edit("用户用途或假设备注",1200);
        readonly FieldEditor fields=new FieldEditor();
        readonly StackPanel article=new StackPanel(), candidates=new StackPanel(), parameterBody=new StackPanel();
        readonly StackPanel searchHeader=new StackPanel();
        readonly WrapPanel readingHeader=new WrapPanel(), bottom=new WrapPanel();
        readonly ScrollViewer scroll;
        readonly TextBlock feedback=UI.Text("",13,UI.Gold);
        readonly Button back, primary, save, more, moreResults;
        readonly List<Button> resultButtons=new List<Button>();
        readonly Dictionary<string,double> positions=new Dictionary<string,double>();
        readonly Dictionary<string,bool> openedSections=new Dictionary<string,bool>();
                Dictionary<string,object> state=new Dictionary<string,object>();
        bool rendering,changed;
        string mode="search", rowsSignature="", articleSignature="", entry="";
        long draftRevision;
        public bool Dirty;
        public UIElement Editable { get { return this; } }

        public LookupForm(Helper host) {
            Host=host;
            RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            RowDefinitions.Add(new RowDefinition());
            RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            search.ToolTip="搜索名称、别名或用途 · ↓进入结果 · Enter打开首项";
            searchHeader.Children.Add(search);
            var hint=UI.Text("物品、怪物、技能 · 支持别名与用途",12,UI.Muted); hint.Margin=new Thickness(0,5,0,8); searchHeader.Children.Add(hint);
            Children.Add(searchHeader);
            back=UI.Button("‹ 返回结果",delegate { SetMode("search"); search.Focus(); });
            more=UI.Button("条目操作…",ShowActions);
            foreach(var button in new[]{back,more}) { button.MinHeight=28; button.Padding=new Thickness(8,3,8,3); button.Margin=new Thickness(0,0,6,4); }
            back.Background=more.Background=Brushes.Transparent;
            readingHeader.Children.Add(back); readingHeader.Children.Add(more); readingHeader.Visibility=Visibility.Collapsed; Children.Add(readingHeader);
            moreResults=UI.Button("显示更多资料",delegate { Host.Send("more","surface","lookup"); });
            scroll=UI.Scroll(candidates); Grid.SetRow(scroll,1); Children.Add(scroll);
            primary=UI.Button("调整条件",delegate { if(mode=="edit") Calculate(); else { SetMode("edit"); fields.MoveFocus(new TraversalRequest(FocusNavigationDirection.First)); } },true);
            save=UI.Button("保存方案…",delegate { FlushEdit(); Host.Send("save_plan","surface","lookup"); });
            bottom.Children.Add(primary); bottom.Children.Add(save); bottom.Margin=new Thickness(0,8,0,0); var footer=UI.Stack(feedback,bottom); Grid.SetRow(footer,2); Children.Add(footer); bottom.Visibility=Visibility.Collapsed; feedback.Visibility=Visibility.Collapsed;
            fields.Submit=Calculate; fields.Changed=delegate { Edited(); };
            note.AcceptsReturn=true; note.MinHeight=80; note.TextWrapping=TextWrapping.Wrap; note.TextChanged+=delegate { Edited(false); };
            parameterBody.Children.Add(UI.Text("调整本次参考条件",16)); parameterBody.Children.Add(fields);
            parameterBody.Children.Add(UI.Section("用途与假设备注",UI.Field("备注（可选，未验证）",note),false));
            search.TextChanged+=delegate { if(!rendering && !Host.Frozen) Host.Send("query","surface","lookup","text",search.Text); };
            search.KeyDown+=delegate(object sender,KeyEventArgs e) {
                if(e.Key==Key.Enter) { Host.Send("first","surface","lookup"); e.Handled=true; }
                else if(e.Key==Key.Down && resultButtons.Count>0) { resultButtons[0].Focus(); e.Handled=true; }
            };
        }
        void SetMode(string next) {
            if(next==mode) return;
            positions[mode]=scroll.VerticalOffset; mode=next;
            searchHeader.Visibility=mode=="search" ? Visibility.Visible : Visibility.Collapsed;
            readingHeader.Visibility=mode=="search" ? Visibility.Collapsed : Visibility.Visible;
            scroll.Content=mode=="search" ? (object)candidates : mode=="edit" ? (object)parameterBody : article;
            UpdateActions(); double position; scroll.ScrollToVerticalOffset(positions.TryGetValue(mode,out position) ? position : 0); UI.Fade(scroll);
        }
        void UpdateActions() {
            bool busy=Data.Flag(state,"calculating");
            feedback.Text=Data.Text(state,"parameter_error",busy ? "正在计算…" : "");
            if(feedback.Text.Length==0 && busy) feedback.Text="正在计算…";
            if(feedback.Text.Length==0) feedback.Text=Data.Text(state,"operation_receipt","");
            feedback.Visibility=mode!="search" && feedback.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
            bool hasEntry=Data.Text(state,"entry_id","").Length>0;
            bottom.Visibility=hasEntry && mode!="search" ? Visibility.Visible : Visibility.Collapsed;
            primary.Visibility=Data.Array(state,"fields").Length>0 ? Visibility.Visible : Visibility.Collapsed;
            primary.IsEnabled=!busy; primary.Content=busy ? "正在计算…" : mode=="edit" ? "重新计算" : Data.Flag(state,"needs_calculation") ? "检查条件" : "调整条件"; UI.Name(primary,Convert.ToString(primary.Content));
            save.IsEnabled=Data.Flag(state,"can_save"); save.ToolTip=save.IsEnabled ? "保存当前数值与条件" : "先补全条件并计算有效结果";
            System.Windows.Controls.ToolTipService.SetShowOnDisabled(save,true); System.Windows.Automation.AutomationProperties.SetHelpText(save,Convert.ToString(save.ToolTip));
        }
        void Calculate() { if(Host.Frozen || Data.Flag(state,"calculating") || Data.Text(state,"entry_id","").Length==0) return; FlushEdit(); state["calculating"]=true; state["parameter_error"]=""; state["can_save"]=false; UpdateActions(); Host.Send("calculate","surface","lookup"); }
        void Edited(bool resultChanged=true) {
            if(rendering || Host.Frozen) return; ++draftRevision; changed=Dirty=true;
            if(resultChanged) { state["calculating"]=false; state["parameter_error"]=""; state["needs_calculation"]=true; state["can_save"]=false; articleSignature=""; article.Children.Clear();
                article.Children.Add(UI.Text("条件已修改",17)); article.Children.Add(UI.Text("旧结果已收起。重新计算后查看本次结果。",13,UI.Gold)); }
            UpdateActions(); FlushEdit();
        }
        public Dictionary<string,object> Raw() { var raw=Data.Map("values",fields.Raw(),"note",UI.Note(note.Text),"draft_revision",draftRevision); Host.CaptureSaveDraft(raw); return raw; }
        public void FlushEdit() { if(!changed) return; changed=false; var raw=Raw(); Host.Send("edit","surface","lookup","values",raw["values"],"note",raw["note"],"draft_revision",draftRevision); }
        public void FocusSearch() { SetMode("search"); search.Focus(); search.SelectAll(); }
        void ShowActions() {
            bool valid=Data.Flag(state,"can_save"), hasEntry=Data.Text(state,"entry_id","").Length>0;
            var items=new List<MenuItem>();
            foreach(string[] pair in new[]{new[]{Data.Flag(state,"favorite") ? "取消收藏" : "收藏此条目","favorite"},new[]{Data.Flag(state,"has_saved_plan") ? "更新或另存方案…" : "保存方案…","save_plan"},new[]{"我的方案…","choose_plan"},new[]{"重新读取当前方案","reload_plan"},new[]{"固定此结果到游戏速查","pin"},new[]{"清除速查固定","clear_pin"},new[]{"撤回本次条件带入","undo_import"},new[]{"带入最新已知角色条件","use_latest"},new[]{"条件与来源详情…","provenance"}}) {
                string action=pair[1]; bool enabled=action=="undo_import" ? Data.Flag(state,"undo") : action=="use_latest" ? Data.Flag(state,"can_latest") : action=="save_plan" || action=="pin" ? valid : action=="favorite" || action=="provenance" ? hasEntry : action=="reload_plan" ? Data.Flag(state,"has_saved_plan") : true;
                items.Add(UI.Item(pair[0],delegate { FlushEdit(); Host.Send(action,"surface","lookup"); },enabled));
            }
            items.Add(UI.Item("方案与收藏（完整面板）",delegate { Host.Send("panel","page","workspace"); })); UI.Menu(more,items.ToArray());
        }
        static Grid LabeledValues(object[] values) {
            var grid=new Grid { Margin=new Thickness(0,4,0,8) }; grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1.05,GridUnitType.Star) }); int index=0;
            foreach(object raw in values) {
                var value=raw as Dictionary<string,object>; if(value==null) continue; grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
                var label=UI.Text(Data.Text(value,"label",""),13,UI.Muted); label.Margin=new Thickness(0,5,10,5); Grid.SetRow(label,index); grid.Children.Add(label);
                string unit=Data.Text(value,"unit",""); var number=UI.Text(Data.Text(value,"value","?")+(unit.Length>0 ? " "+unit : ""),14); number.FontWeight=FontWeights.SemiBold;
                var body=UI.Stack(number); string condition=Data.Text(value,"condition",""); if(condition.Length>0) body.Children.Add(UI.Text(condition,12,UI.Muted));
                body.Margin=new Thickness(0,4,0,6); Grid.SetRow(body,index++); Grid.SetColumn(body,1); grid.Children.Add(body);
            } return grid;
        }
        Expander RememberSection(string identity,string title,UIElement body,bool initial) {
            bool open; if(!openedSections.TryGetValue(identity,out open)) open=initial; var section=UI.Section(title,body,open);
            section.Expanded+=delegate { openedSections[identity]=true; }; section.Collapsed+=delegate { openedSections[identity]=false; }; return section;
        }
        void RenderArticle(Dictionary<string,object> data) {
            string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(Data.Map("entry",Data.Text(data,"entry_id",""),"sections",Data.Array(data,"numeric_sections"),"summary",Data.Array(data,"primary_values"),"note",Data.Text(data,"primary_note",""),"text",Data.Text(data,"result",""),"origin",Data.Text(data,"origin_brief",""),"status",Data.Text(data,"status","")));
            if(signature==articleSignature) return; articleSignature=signature; article.Children.Clear();
            string identity=Data.Text(data,"entry_id",""), name=Data.Text(data,"entry_name",""); object[] sections=Data.Array(data,"numeric_sections"), main=Data.Array(data,"primary_values");
            if(name.Length>0) { var title=new DockPanel(); var picture=UI.Artwork(Data.Object(data,"artwork"),24); DockPanel.SetDock(picture,Dock.Left); title.Children.Add(picture); var nameText=UI.Text(name,17); nameText.FontWeight=FontWeights.SemiBold; nameText.VerticalAlignment=VerticalAlignment.Center; title.Children.Add(nameText); title.Margin=new Thickness(0,0,0,4); article.Children.Add(title); }
            var origin=UI.Text(Data.Text(data,"origin_brief","参考条件"),12,UI.Muted); origin.Margin=new Thickness(0,0,0,2); article.Children.Add(origin);
            if(main.Length>0) {
                var grid=new Grid { Margin=new Thickness(0,0,0,10) };
                for(int i=0;i<main.Length;i++) {
                    grid.ColumnDefinitions.Add(new ColumnDefinition()); var value=(Dictionary<string,object>)main[i];
                    var number=UI.Text(Data.Text(value,"value","?")+" "+Data.Text(value,"unit",""),25); number.LineHeight=30; number.FontWeight=FontWeights.SemiBold;
                    var cell=UI.Stack(UI.Text(Data.Text(value,"label",""),12,UI.Muted),number); cell.Margin=new Thickness(0,0,8,0); Grid.SetColumn(cell,i); grid.Children.Add(cell);
                } article.Children.Add(grid);
                string caution=Data.Text(data,"primary_note",""); if(caution.Length>0) { var noteText=UI.Text(caution,12,UI.Muted); noteText.Margin=new Thickness(0,0,0,12); article.Children.Add(noteText); }
            }
            if(sections.Length==0) { var text=new StackPanel(); UI.Article(text,Data.Text(data,"result","")); article.Children.Add(text); }
            foreach(object raw in sections) {
                var section=raw as Dictionary<string,object>; if(section==null) continue;
                string title=Data.Text(section,"title","数值"), key=identity+"/"+Data.Text(section,"index","");
                object[] values=Data.Array(section,"values"), selected=Data.Array(section,"selected_values"), columns=Data.Array(section,"columns"), rows=Data.Array(section,"rows");
                if(values.Length>0 || selected.Length>0) article.Children.Add(RememberSection(key+"/current",title+(selected.Length>0 ? " · 当前条件" : ""),UI.Stack(LabeledValues(values),LabeledValues(selected)),main.Length==0));
                if(columns.Length>0 && rows.Length>0) {
                    var table=new StackPanel(); int rowIndex=0;
                    foreach(object rawRow in rows) {
                        var cells=rawRow as object[]; if(cells==null) continue; var labeled=new List<object>();
                        for(int i=0;i<Math.Min(columns.Length,cells.Length);i++) labeled.Add(Data.Map("label",Convert.ToString(columns[i]),"value",Convert.ToString(cells[i])));
                        string rowTitle=Convert.ToString(columns[0])+" "+(cells.Length>0 ? Convert.ToString(cells[0]) : "");
                        bool current=section.ContainsKey("selected_row") && section["selected_row"]!=null && Data.Number(section,"selected_row")==rowIndex;
                        if(current) rowTitle+=" · 当前条件";
                        table.Children.Add(RememberSection(key+"/row/"+rowIndex,rowTitle,LabeledValues(labeled.ToArray()),current)); rowIndex++;
                    } article.Children.Add(RememberSection(key+"/table","完整"+title+" · "+rows.Length+"行",table,false));
                }
                string noteText=Data.Text(section,"note",""); if(noteText.Length>0) article.Children.Add(RememberSection(key+"/note",title+" · 适用条件",UI.Text(noteText),false));
            }
            var provenance=new StackPanel(); provenance.Children.Add(UI.Text(Data.Text(data,"status",""),12,UI.Muted));
            string prose=Data.Text(data,"result_prose",""); if(prose.Length>0) UI.Article(provenance,prose+"\n\n"+Data.Text(data,"status",""));
            int sourceIndex=0; string token=Data.Text(data,"sources_token","");
            foreach(object raw in Data.Array(data,"sources")) { var link=(Dictionary<string,object>)raw; int index=sourceIndex++; provenance.Children.Add(UI.Button("官方依据 · "+Data.Text(link,"label",""),delegate { Host.Send("source_link","surface","lookup","index",index,"token",token); })); }
            article.Children.Add(RememberSection(identity+"/provenance","来源、条件与备注",provenance,false));
        }
        public void Render(Dictionary<string,object> d) {
            if(Data.Number(d,"draft_revision")<draftRevision) return;
            rendering=true; try {
                state=d; draftRevision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty");
                if(!search.IsKeyboardFocused) UI.Replace(search,Data.Text(d,"query",""));
                var rows=Data.Array(d,"rows"); string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(rows)+Data.Flag(d,"can_more");
                if(signature!=rowsSignature) {
                    int focused=resultButtons.FindIndex(delegate(Button b) { return b.IsKeyboardFocusWithin; }); candidates.Children.Clear(); resultButtons.Clear();
                    foreach(object item in rows) {
                        var row=(Dictionary<string,object>)item; int index=resultButtons.Count; string token=Data.Text(row,"token","");
                        var button=UI.Button("",delegate { if(!Host.Frozen) Host.Send("select","surface","lookup","index",index,"token",token); });
                        string text=Data.Text(row,"text",""); button.Content=UI.ImageRow(text,Data.Object(row,"artwork")); UI.Name(button,text); button.HorizontalContentAlignment=HorizontalAlignment.Stretch;
                        button.KeyDown+=delegate(object sender,KeyEventArgs e) { if(e.Key==Key.Down && index+1<resultButtons.Count) { resultButtons[index+1].Focus(); e.Handled=true; } else if(e.Key==Key.Up) { if(index>0) resultButtons[index-1].Focus(); else search.Focus(); e.Handled=true; } };
                        resultButtons.Add(button); candidates.Children.Add(button);
                    }
                    if(rows.Length==0) candidates.Children.Add(UI.Text("没有匹配条目。试试别名或用途，或清空搜索。",13,UI.Muted));
                    if(Data.Flag(d,"can_more")) candidates.Children.Add(moreResults);
                    if(focused>=0 && focused<resultButtons.Count && mode=="search") resultButtons[focused].Focus(); rowsSignature=signature;
                }
                object[] specs=Data.Array(d,"fields"); var rawValues=new Dictionary<string,object>();
                foreach(object item in specs) { var spec=(Dictionary<string,object>)item; rawValues[Data.Text(spec,"key","")]=Data.Text(spec,"raw",""); }
                fields.Render(specs,rawValues,true); UI.Replace(note,Data.Text(d,"note","")); RenderArticle(d);
                string nextEntry=Data.Text(d,"entry_id","");
                if(nextEntry!=entry) { positions.Remove("result"); positions.Remove("edit"); entry=nextEntry; }
                if(Data.Flag(d,"focus_result")) { SetMode("result"); scroll.ScrollToTop(); Dispatcher.BeginInvoke(new Action(delegate { if(primary.IsVisible) primary.Focus(); else back.Focus(); })); }
                else if(nextEntry.Length==0 && mode!="search") SetMode("search");
                UpdateActions();
            } finally { rendering=false; }
        }
    }

    sealed class SettingsForm : Grid {
        readonly Helper Host;
        readonly StackPanel body=new StackPanel();
        readonly Dictionary<string,Control> values=new Dictionary<string,Control>();
        readonly Dictionary<string,TextBox> bindings=new Dictionary<string,TextBox>();
        readonly TextBlock status=UI.Text("",12,UI.Muted), feedback=UI.Text("",12,UI.Gold);
        readonly WrapPanel persistence;
        bool rendering,changed,initialized;
        long draftRevision;
        public bool Dirty;
        public FrameworkElement Connection;
        public UIElement Editable { get { return this; } }
        Expander connectionSection;
        public void Prepend(FrameworkElement connection) { connectionSection=UI.Section("连接与启动 · 更改后立即应用",connection,false); body.Children.Insert(0,connectionSection); }
        public void OpenConnection() { if(connectionSection!=null) { connectionSection.IsExpanded=true; connectionSection.BringIntoView(); } }
        public SettingsForm(Helper host) {
            Host=host; RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); var scroll=UI.Scroll(body); Children.Add(scroll);
            body.Children.Add(UI.Text("游戏提示与快捷键",16)); body.Children.Add(UI.Text("以下修改点击保存后应用。随行窗口可直接拖动、缩放；这里配置的是独立的游戏内短提示。",13,UI.Muted));
            foreach(string[] pair in new[]{new[]{"enabled","启用游戏提示"},new[]{"alerts","新存档新风险短暂提示"}}) { var check=UI.Name(new CheckBox { Content=pair[1] },pair[1]); values[pair[0]]=check; body.Children.Add(check); check.Checked+=delegate { Edited(); }; check.Unchecked+=delegate { Edited(); }; }
            body.Children.Add(UI.Text("仅跟随游戏前台，显示最近保存的参考数据。",11,UI.Muted)); var display=new StackPanel(); var anchor=UI.Combo("显示角落","左上","右上","左下","右下"); values["anchor"]=anchor; anchor.SelectionChanged+=delegate { Edited(); }; display.Children.Add(UI.Field("显示角落",anchor));
            foreach(string[] pair in new[]{new[]{"offset_x","横向边距"},new[]{"offset_y","纵向边距"},new[]{"font_scale","字号倍率（1–2）"},new[]{"opacity","背景不透明度（0.5–1）"},new[]{"notice_seconds","短提醒时长（3–30秒）"}}) { var edit=UI.Edit(pair[1],80); values[pair[0]]=edit; edit.TextChanged+=delegate { Edited(); }; display.Children.Add(UI.Field(pair[1],edit)); } body.Children.Add(UI.Section("游玩显示",display,true));
            var shortcuts=new StackPanel(); shortcuts.Children.Add(UI.Text("可以修改或清空禁用；快捷键需含 Ctrl 或 Alt。",11,UI.Muted)); foreach(string[] pair in new[]{new[]{"capture","立即备份已保存进度"},new[]{"show","显示随行助手"},new[]{"library","手册"},new[]{"backups","存档历史"},new[]{"play_toggle","开关游戏提示"},new[]{"quick","收起或展开随行助手"}}) { var edit=UI.Edit(pair[1]+"快捷键",80); bindings[pair[0]]=edit; edit.TextChanged+=delegate { Edited(); }; shortcuts.Children.Add(UI.Field(pair[1],edit)); } body.Children.Add(UI.Section("全局快捷键",shortcuts,false)); body.Children.Add(UI.Section("保存与注册状态",status,true));
            persistence=UI.Buttons(UI.Button("保存提示与快捷键",delegate { FlushEdit(); Host.Send("settings_save","surface","settings"); },true),UI.Button("更多",delegate { var button=(Button)persistence.Children[1]; UI.Menu(button,UI.Item("重新读取提示与快捷键",delegate { FlushEdit(); Host.Send("settings_reload","surface","settings"); }),UI.Item("拖动游戏提示位置",delegate { FlushEdit(); Host.Send("unlock","surface","settings"); }),UI.Item("完整设置面板",delegate { Host.Send("panel","page","play-settings"); })); })); persistence.Margin=new Thickness(0,10,0,0); var bottom=UI.Stack(feedback,persistence); Grid.SetRow(bottom,1); Children.Add(bottom);
        }
        void Edited() { if(rendering || !initialized || Host.Frozen) return; ++draftRevision; changed=Dirty=true; feedback.Text="已修改，尚未保存"; FlushEdit(); }
        public Dictionary<string,object> Raw() { var v=new Dictionary<string,object>(); var b=new Dictionary<string,object>(); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; v[pair.Key]=check!=null ? (object)(check.IsChecked==true) : combo!=null ? Convert.ToString(combo.SelectedItem) : text.Text; } foreach(var pair in bindings) b[pair.Key]=pair.Value.Text; return Data.Map("values",v,"bindings",b,"draft_revision",draftRevision); }
        public void FlushEdit() { if(!initialized || !changed) return; changed=false; var raw=Raw(); Host.Send("settings_edit","surface","settings","values",raw["values"],"bindings",raw["bindings"],"draft_revision",draftRevision); }
        public void Render(Dictionary<string,object> d) { persistence.IsEnabled=!Data.Flag(d,"io_busy"); if(Data.Number(d,"draft_revision")<draftRevision) return; rendering=true; try { draftRevision=Data.Number(d,"draft_revision"); var v=Data.Object(d,"values"); var b=Data.Object(d,"bindings"); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; if(check!=null) check.IsChecked=Data.Flag(v,pair.Key); else if(combo!=null) { string value=Data.Text(v,pair.Key,""); if(!combo.Items.Contains(value)) combo.Items.Add(value); combo.SelectedItem=value; } else UI.Replace(text,Data.Text(v,pair.Key,"")); } foreach(var pair in bindings) UI.Replace(pair.Value,Data.Text(b,pair.Key,"")); feedback.Text=Data.Text(d,"status",""); status.Text=feedback.Text+"\n\n"+Data.Text(d,"registration",""); Dirty=Data.Flag(d,"dirty"); initialized=true; } finally { rendering=false; } }
    }

    sealed class PlansForm : Grid {
        readonly Helper Host; readonly TextBox search=UI.Edit("按方案名称或备注搜索",200);
        readonly ComboBox kind=UI.Combo("方案类型","全部类型","数值方案","装备方案","炼金方案","手动草稿","角色条件"), order=UI.Combo("方案排序","最近更新","名称");
        readonly StackPanel rows=new StackPanel(); bool rendering;
        public PlansForm(Helper host) { Host=host; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); var filters=UI.Stack(UI.Field("搜索方案",search),UI.Field("类型",kind),UI.Field("排序",order)); var fold=UI.Section("筛选我的方案",filters,false); Children.Add(fold); var scroll=UI.Scroll(rows); Grid.SetRow(scroll,1); Children.Add(scroll); search.TextChanged+=delegate { Filter(); }; kind.SelectionChanged+=delegate { Filter(); }; order.SelectionChanged+=delegate { Filter(); }; }
        void Filter() { if(!rendering && !Host.Frozen) Host.Send("filter_plans","surface","lookup","query",search.Text,"kind",Convert.ToString(kind.SelectedItem),"order",Convert.ToString(order.SelectedItem)); }
        public void Render(Dictionary<string,object> d) { rendering=true; try { rows.Children.Clear(); foreach(object item in Data.Array(d,"rows")) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""); var button=UI.Button("",delegate { if(!Host.Frozen) Host.Send("open_plan","surface","lookup","id",id); }); string text=Data.Text(row,"text",""); button.Content=UI.ImageRow(text,Data.Object(row,"artwork")); UI.Name(button,text); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; rows.Children.Add(button); } if(rows.Children.Count==0) rows.Children.Add(UI.Text("没有匹配的方案。可以修改筛选，或先保存一个方案。",13,UI.Muted)); } finally { rendering=false; } }
    }
}
