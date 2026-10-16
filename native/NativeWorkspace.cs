using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Web.Script.Serialization;

namespace Denghuo.Native {
    // Raw text is never parsed by the presentation; hidden fields survive structural edits.
    sealed class FieldEditor : StackPanel {
        readonly Dictionary<string,FrameworkElement> controls = new Dictionary<string,FrameworkElement>();
        readonly Dictionary<string,TextBlock> hints = new Dictionary<string,TextBlock>();
        readonly Dictionary<string,bool> expanded = new Dictionary<string,bool>();
        readonly StackPanel helpBody = new StackPanel();
        Expander helpDetails;
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
                } if(helpDetails!=null) helpDetails.Content=null; helpDetails=UI.Section("输入说明与来源",helpBody,expanded.ContainsKey("__help") && expanded["__help"]); helpDetails.Expanded+=delegate { expanded["__help"]=true; }; helpDetails.Collapsed+=delegate { expanded["__help"]=false; }; Children.Add(helpDetails); signature=next; }
                helpBody.Children.Clear();
                foreach(object item in fields) { var spec=(Dictionary<string,object>)item; string key=Data.Text(spec,"key",""), value=Data.Text(values,key,Data.Text(spec,"raw","")); var control=controls[key]; var text=control as TextBox; var combo=control as ComboBox; var multi=control as StackPanel;
                    if(text!=null) UI.Replace(text,value); else if(combo!=null) { int found=-1; for(int i=0;i<combo.Items.Count;i++) if(((Choice)combo.Items[i]).Id==value) found=i; if(found<0) found=combo.Items.Add(new Choice(value,"需核对的原始输入："+value)); combo.SelectedIndex=found; }
                    else if(multi!=null) { var selected=new HashSet<string>(value.Split('|')); foreach(string id in selected) { bool found=id.Length==0; foreach(CheckBox check in multi.Children) if((string)check.Tag==id) found=true; if(!found) { var check=UI.Name(new CheckBox { Content=UI.Text("需核对的原始实例："+id),Tag=id },"需核对的原始实例："+id); check.Checked+=delegate { Edited(key,false); }; check.Unchecked+=delegate { Edited(key,false); }; multi.Children.Add(check); } } foreach(CheckBox check in multi.Children) check.IsChecked=selected.Contains((string)check.Tag); }
                    string help=numeric ? Data.Text(spec,"origin","")+(key=="corrosion_public" ? " · 游戏显示值给范围；精确值仅为手填假设" : " · "+Data.Text(spec,"min","")+"–"+Data.Text(spec,"max","")) : Data.Text(spec,"help",""); hints[key].Text=help; hints[key].Visibility=help.Length>0 && (Data.Flag(spec,"help_visible") || numeric && (value.Trim().Length==0 || key=="corrosion_public")) ? Visibility.Visible : Visibility.Collapsed; control.ToolTip=help; System.Windows.Automation.AutomationProperties.SetHelpText(control,help);
                    if(help.Length>0) { var line=UI.Text(Data.Text(spec,"label",key)+" · "+help,12,UI.Muted); line.Margin=new Thickness(0,0,0,8); helpBody.Children.Add(line); }
                }
                if(helpDetails!=null) helpDetails.Visibility=helpBody.Children.Count>0 ? Visibility.Visible : Visibility.Collapsed;
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
        readonly StackPanel backupSummary=new StackPanel();
        readonly StackPanel taskContext=new StackPanel();
        readonly Dictionary<string,ComboBox> quickChoices=new Dictionary<string,ComboBox>();
        readonly Dictionary<string,Button> targetControls=new Dictionary<string,Button>();
        object[] currentSpecs=new object[0];
        string quickSignature="", pendingEditorSection="";
        readonly TextBlock mapLegend=UI.Text("金色：角色 · 绿色：楼梯 · 深色：未探索\n棕色×：陷阱 · 蓝色横线：水地 · 深灰：障碍\n蓝色圆圈：水井 · 空框：失效陷阱 · 紫色×：未识别地形",12,UI.Muted);
        readonly TextBlock mapCoordinates=UI.Text("",12,UI.Muted);
        readonly Expander mapDetails;
        readonly SavedMap map=new SavedMap();
        readonly ScrollViewer scroll;
        readonly WrapPanel actions=new WrapPanel();
        readonly TextBlock notice=UI.Text("",12,UI.Gold);
        readonly TextBlock receiptBrief=UI.Text("",13,UI.Gold);
        Expander receipt;
        readonly TextBlock origin=UI.Text("",12,UI.Muted);
        readonly Button mode;
        readonly Expander selection;
        readonly Expander details;
        readonly Dictionary<string,double> positions=new Dictionary<string,double>();
        readonly Dictionary<string,bool> resultDetailExpanded=new Dictionary<string,bool>();
        readonly Dictionary<string,Control> resultDetailControls=new Dictionary<string,Control>();
        readonly Dictionary<string,Control> resultItemControls=new Dictionary<string,Control>();
        readonly Dictionary<string,bool> resultItemExpanded=new Dictionary<string,bool>();
        string resultItemToken="";
        readonly Dictionary<string,Control> rowControls=new Dictionary<string,Control>();
        readonly Dictionary<string,Control> actionControls=new Dictionary<string,Control>();
        bool rendering,editing,calculated;
        long revision;
        string articleText="", rowSignature="", actionSignature="";
        Dictionary<string,object> values=new Dictionary<string,object>();
        public bool Dirty;
        public TaskPane(Helper owner,string name) {
            host=owner; page=name; Focusable=true; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            mode=UI.Button("编辑条件",delegate { SetEditing(!editing); }); mode.HorizontalAlignment=HorizontalAlignment.Left; mode.Background=Brushes.Transparent; var taskHeader=new WrapPanel(); taskHeader.Children.Add(mode); if(page=="inventory") taskHeader.Children.Add(UI.Button("装备比较 ›",delegate { host.Manager.OpenPage("equipment"); })); if(page=="equipment") taskHeader.Children.Add(UI.Button("选背包装备 ›",delegate { host.Manager.OpenPage("inventory"); }));
            Children.Add(UI.Stack(origin,taskHeader));
            selection=UI.Section(page=="inventory" ? "选择背包物品" : page=="map" ? "选择保存楼层" : "选择存档记录",selector,true); output.Children.Add(selection); if(page=="map") output.Children.Add(article); output.Children.Add(map); mapDetails=UI.Section("图例与坐标",UI.Stack(mapLegend,mapCoordinates),false); output.Children.Add(mapDetails); if(page=="equipment") { output.Children.Add(comparison); details=UI.Section("完整数值与条件",article,true); output.Children.Add(details); } else if(page!="map") output.Children.Add(article); output.Children.Add(resultDetails); scroll=UI.Scroll(output); Grid.SetRow(scroll,1); Children.Add(scroll); actions.Margin=new Thickness(0,10,0,0); if(page=="backups") { receipt=UI.Section("回执详情",notice,false); output.Children.Insert(0,receipt); output.Children.Insert(0,receiptBrief); Grid.SetRow(actions,2); Children.Add(actions); } else { var feedback=UI.Scroll(notice); feedback.MaxHeight=64; var bottom=UI.Stack(feedback,actions); Grid.SetRow(bottom,2); Children.Add(bottom); }
            if(page=="equipment" || page=="alchemy") output.Children.Insert(0,taskContext);
            if(page=="alchemy") { output.Children.Remove(article); output.Children.Insert(0,article); }
            if(page=="backups") output.Children.Insert(0,backupSummary);
            fields.Changed=DraftChanged;
        }
        public void SetPlanMetadata(string name,string note) { fields.SetMetadata(name,note); values=fields.Raw(); Dirty=true; ++revision; Flush(); }
        public Dictionary<string,object> Raw() { return fields.Raw(); }
        public void Flush() { host.Send("game_edit","page",page,"values",Raw(),"draft_revision",revision); }
        string ModeLabel() { return editing ? calculated ? "查看结果" : "返回任务" : page=="equipment" ? "条件与预算" : page=="alchemy" ? "编辑计划条件" : "调整条件"; }
        void SetEditing(bool value) { positions[editing ? "edit" : "result"]=scroll.VerticalOffset; editing=value; mode.Content=ModeLabel(); UI.Name(mode,Convert.ToString(mode.Content)); scroll.Content=editing ? (object)fields : output; double position; scroll.ScrollToVerticalOffset(positions.TryGetValue(editing ? "edit" : "result",out position) ? position : 0); UI.Fade(scroll); }
        void OpenEditor(string section) {
            SetEditing(true);
            foreach(UIElement child in fields.Children) { var group=child as Expander; if(group!=null && System.Windows.Automation.AutomationProperties.GetName(group).StartsWith(section)) { group.IsExpanded=true; var target=group; Dispatcher.BeginInvoke(new Action(delegate { target.BringIntoView(); })); break; } }
        }
        void DraftChanged(string key,bool structural) {
            if(rendering || host.Frozen) return; ++revision; Dirty=true; values=fields.Raw();
            bool metadata=key=="name" || key=="note";
            notice.Text=metadata ? "备注或名称已修改，尚未保存" : "条件已修改，待重新计算"; notice.Visibility=Visibility.Visible;
            if(!metadata) { calculated=false; foreach(string command in new[]{"save","update"}) if(actionControls.ContainsKey(command)) { actionControls[command].IsEnabled=false; actionControls[command].ToolTip="先重新计算有效结果"; } mode.Content=ModeLabel(); UI.Name(mode,Convert.ToString(mode.Content)); articleText="条件已修改，请重新计算。原始输入已保留。"; UI.Article(article,articleText); comparison.Children.Clear(); RenderResultDetails(new object[0]); if(details!=null) details.IsExpanded=true; }
            host.Send("game_edit","page",page,"values",values,"draft_revision",revision,"structure",structural);
        }
        string ChoiceLabel(string key,string fallback) {
            string value=Data.Text(values,key,""); foreach(object raw in currentSpecs) { var spec=(Dictionary<string,object>)raw; if(Data.Text(spec,"key","")!=key) continue; foreach(object option in Data.Array(spec,"choices")) { var choice=(Dictionary<string,object>)option; if(Data.Text(choice,"id","")==value) return Data.Text(choice,"text",fallback); } }
            return value.Length>0 ? "需核对："+value : fallback;
        }
        void RenderTaskContext() {
            if(page=="equipment") {
                var selectedSpecs=new List<Dictionary<string,object>>(); foreach(object raw in currentSpecs) { var spec=(Dictionary<string,object>)raw; string key=Data.Text(spec,"key",""); if(key=="id_a" || key=="id_b") selectedSpecs.Add(spec); }
                // Raw changes do not recreate focused selectors; only the choice contract does.
                var shape=new List<object>(); foreach(var spec in selectedSpecs) shape.Add(Data.Map("key",Data.Text(spec,"key",""),"choices",Data.Array(spec,"choices"))); string next=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(shape);
                if(next!=quickSignature) { taskContext.Children.Clear(); quickChoices.Clear(); var pair=new UniformGrid { Columns=2,Margin=new Thickness(0,0,0,8) };
                    foreach(var spec in selectedSpecs) { string key=Data.Text(spec,"key",""); var combo=UI.Combo("选择装备 "+(key=="id_a" ? "A" : "B")); combo.MinWidth=0; combo.FontSize=13; combo.ToolTip="选择已知装备或明确手填假设；未鉴定背包实例需主动揭示。"; foreach(object raw in Data.Array(spec,"choices")) { var choice=(Dictionary<string,object>)raw; string id=Data.Text(choice,"id",""); combo.Items.Add(new Choice(id,id.Length==0 ? "选择装备" : Data.Text(choice,"text",""))); }
                        combo.SelectionChanged+=delegate { if(rendering || host.Frozen) return; var choice=combo.SelectedItem as Choice; if(choice==null) return; values=fields.Raw(); values[key]=choice.Id; fields.Render(currentSpecs,values); DraftChanged(key,true); };
                        quickChoices[key]=combo; var body=UI.Stack(UI.Text(key=="id_a" ? "装备 A" : "装备 B",13,UI.Muted),combo); body.Margin=new Thickness(0,0,6,0); pair.Children.Add(body);
                    } taskContext.Children.Add(pair); quickSignature=next;
                }
                foreach(var item in quickChoices) { string raw=Data.Text(values,item.Key,""); int found=-1; for(int i=0;i<item.Value.Items.Count;i++) if(((Choice)item.Value.Items[i]).Id==raw) found=i; if(found<0) found=item.Value.Items.Add(new Choice(raw,"需核对的原始输入："+raw)); item.Value.SelectedIndex=found; }
            } else if(page=="alchemy") {
                var priorFocus=Keyboard.FocusedElement; var previous=new Dictionary<string,Control>(); foreach(var item in targetControls) previous[item.Key]=item.Value;
                taskContext.Children.Clear(); var nextControls=new Dictionary<string,Button>(); int targets; if(!Int32.TryParse(Data.Text(values,"targets","0"),out targets)) targets=0;
                for(int i=0;i<targets && i<64;i++) { string key="t"+i+".recipe", identity="target-"+i, section="产出目标 "+(i+1)+" ·"; Button button;
                    if(!targetControls.TryGetValue(identity,out button)) button=UI.Button("",delegate { if(!host.Frozen) OpenEditor(section); });
                    string label=calculated ? "编辑目标"+(targets>1 ? " "+(i+1) : "")+" ›" : (targets>1 ? (i+1)+". " : "目标 · ")+ChoiceLabel(key,"尚未选择配方")+" ×"+Data.Text(values,"t"+i+".quantity","")+" ›";
                    button.Content=UI.Text(label,14); UI.Name(button,"编辑"+label.TrimEnd(' ','›')); button.Background=Brushes.Transparent; button.HorizontalContentAlignment=HorizontalAlignment.Left; button.Padding=new Thickness(0,5,6,5); taskContext.Children.Add(button); nextControls[identity]=button;
                }
                if(targets==0) taskContext.Children.Add(UI.Text("尚无目标 · 点击增加目标",14,UI.Gold));
                int resources; if(!Int32.TryParse(Data.Text(values,"resources","0"),out resources)) resources=0; int known=0; for(int i=0;i<resources && i<256;i++) if(Data.Text(values,"r"+i+".origin","")=="known") known++;
                string stock=resources==0 && Data.Text(values,"energy_origin","")!="known" ? "未带入库存" : known==resources ? "已知库存 "+known+" 项" : "已知库存 "+known+" 项 · 手填 "+(resources-known)+" 项";
                string energy=Data.Text(values,"energy",""); string budget=energy.Trim().Length==0 ? "能量未确认" : (Data.Text(values,"energy_origin","")=="known" ? "已知能量 " : "手填能量 ")+energy;
                taskContext.Children.Add(UI.Text(stock+" · "+budget,13,UI.Muted)); taskContext.Margin=new Thickness(0,0,0,10);
                targetControls.Clear(); var retained=new Dictionary<string,Control>(); foreach(var item in nextControls) { targetControls[item.Key]=item.Value; retained[item.Key]=item.Value; } host.Manager.RebindTaskFocus(page,previous,retained,this,priorFocus);
            }
        }
        void RenderFloorItems(StackPanel body, Dictionary<string,object> detail) {
            string token=Data.Text(detail,"token","");
            if(token!=resultItemToken) { resultItemExpanded.Clear(); resultItemToken=token; }
            body.Children.Clear(); resultItemControls.Clear();
            foreach(object raw in Data.Array(detail,"items")) {
                var item=(Dictionary<string,object>)raw; string id=Data.Text(item,"id",""), label=Data.Text(item,"summary","");
                var content=new StackPanel(); UI.Article(content,Data.Text(item,"text",""));
                var button=UI.Button("查看物品数值",delegate { if(!host.Frozen) host.Send("game_action","page","map","command","map_item_reference","id",id,"token",token); });
                button.IsEnabled=Data.Flag(item,"can_reference");
                if(!button.IsEnabled) { button.Content="暂无数值资料"; button.ToolTip="可展开阅读已保存的属性与说明"; }
                content.Children.Add(button); resultItemControls[id+"/numeric"]=button;
                bool expanded; resultItemExpanded.TryGetValue(id,out expanded);
                var section=UI.Section(label,content,expanded); section.Header=UI.ImageRow(label+"\n"+Data.Text(item,"location",""),Data.Object(item,"artwork"));
                section.Expanded+=delegate { resultItemExpanded[id]=true; };
                section.Collapsed+=delegate { resultItemExpanded[id]=false; };
                UI.Name(section,label+" · "+Data.Text(item,"location",""));
                resultItemControls[id+"/details"]=section; body.Children.Add(section);
            }
            if(!Data.Flag(detail,"previous") && !Data.Flag(detail,"next")) return;
            var navigation=new WrapPanel { Margin=new Thickness(0,8,0,0) };
            foreach(string direction in new[]{"previous","next"}) {
                string command="map_items_"+direction;
                var button=UI.Button(direction=="previous" ? "上一页" : "下一页",delegate { if(!host.Frozen) host.Send("game_action","page","map","command",command,"token",token); });
                button.IsEnabled=Data.Flag(detail,direction); navigation.Children.Add(button); resultItemControls[command]=button;
            }
            navigation.Children.Add(UI.Text(Data.Text(detail,"range",""),12,UI.Muted)); body.Children.Add(navigation);
        }
        void RenderResultDetails(object[] rows) {
            var priorFocus=Keyboard.FocusedElement;
            var previous=new Dictionary<string,Control>(resultDetailControls);
            foreach(var item in resultItemControls) previous[item.Key]=item.Value;
            resultDetailControls.Clear(); int index=0; bool hasItems=false;
            foreach(object raw in rows) {
                var extra=raw as Dictionary<string,object>; if(extra==null) continue;
                string identity=Data.Text(extra,"id","detail-"+index), title=Data.Text(extra,"title","详细记录"), text=Data.Text(extra,"text","");
                Control retained; Expander section;
                if(previous.TryGetValue(identity,out retained)) section=(Expander)retained;
                else {
                    bool expanded; if(!resultDetailExpanded.TryGetValue(identity,out expanded)) expanded=Data.Flag(extra,"expanded");
                    section=UI.Section(title,new StackPanel(),expanded);
                    section.Expanded+=delegate { resultDetailExpanded[identity]=true; };
                    section.Collapsed+=delegate { resultDetailExpanded[identity]=false; };
                }
                if(System.Windows.Automation.AutomationProperties.GetName(section)!=title) { section.Header=UI.Text(title,13,UI.Gold); UI.Name(section,title); }
                bool items=identity=="map_items"; hasItems=hasItems || items;
                string signature=items ? new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(extra) : text;
                if(!Object.Equals(section.Tag,signature)) {
                    if(items) RenderFloorItems((StackPanel)section.Content,extra);
                    else UI.Article((StackPanel)section.Content,text);
                    section.Tag=signature;
                }
                // Keep the actual header ToggleButton across ordinary source refreshes.
                if(resultDetails.Children.IndexOf(section)!=index) { resultDetails.Children.Remove(section); resultDetails.Children.Insert(index,section); }
                resultDetailControls[identity]=section; index++;
            }
            while(resultDetails.Children.Count>index) resultDetails.Children.RemoveAt(index);
            if(!hasItems) { resultItemControls.Clear(); resultItemExpanded.Clear(); resultItemToken=""; }
            var retainedControls=new Dictionary<string,Control>(resultDetailControls);
            foreach(var item in resultItemControls) retainedControls[item.Key]=item.Value;
            host.Manager.RebindTaskFocus(page,previous,retainedControls,this,priorFocus);
        }
        void RenderComparison(Dictionary<string,object> data) {
            comparison.Children.Clear(); var choices=Data.Array(data,"choices"); var planning=Data.Object(data,"planning");
            string detailLabel=planning.Count>0 ? "完整比较与预算" : "完整数值与条件"; details.Header=UI.Text(detailLabel,13,UI.Gold); UI.Name(details,detailLabel);
            details.Visibility=calculated ? Visibility.Visible : Visibility.Collapsed; details.IsExpanded=choices.Length!=2; if(choices.Length!=2) return;
            var identities=new UniformGrid { Columns=2, Margin=new Thickness(0,0,0,6) };
            for(int i=0;i<choices.Length;i++) {
                var choice=(Dictionary<string,object>)choices[i];
                var identity=new DockPanel { Margin=new Thickness(0,0,6,0) };
                var picture=UI.Artwork(Data.Object(choice,"artwork"),16); DockPanel.SetDock(picture,Dock.Left); identity.Children.Add(picture);
                var name=UI.Text((i==0 ? "A · " : "B · ")+Data.Text(choice,"summary_name",Data.Text(choice,"name","")),13); name.FontWeight=FontWeights.SemiBold; name.VerticalAlignment=VerticalAlignment.Center; identity.Children.Add(name); identities.Children.Add(identity);
            }
            comparison.Children.Add(identities);
            string context=Data.Text(data,"summary_context",""); if(context.Length>0) comparison.Children.Add(UI.Text(context,12,UI.Gold));
            var branches=Data.Array(data,"summary_branches");
            if(branches.Length==0) comparison.Children.Add(UI.Text("基础参考 · 当前 → 升级一次",12,UI.Muted));
            else foreach(object branch in branches) comparison.Children.Add(UI.Text(Convert.ToString(branch),12,UI.Gold));
            var primary=new List<Dictionary<string,object>>();
            foreach(object item in Data.Array(data,"summary_rows")) primary.Add((Dictionary<string,object>)item);
            var grid=new Grid { Margin=new Thickness(0,4,0,8) }; grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1.1,GridUnitType.Star) }); grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition());
            int row=0; foreach(var metric in primary) {
                var cells=Data.Array(metric,"values"); if(cells.Length!=4) continue;
                grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); string unit=Data.Text(metric,"unit","");
                var label=UI.Text(Data.Text(metric,"label","")+(unit.Length>0 ? " · "+unit : ""),12,UI.Muted); label.Margin=new Thickness(0,5,6,5); Grid.SetRow(label,row); grid.Children.Add(label);
                for(int i=0;i<2;i++) {
                    string current=Convert.ToString(cells[i*2]), upgraded=Convert.ToString(cells[i*2+1]);
                    var value=UI.Text(current==upgraded ? current : current+"→"+upgraded.Replace(" / ","/"),13);
                    value.VerticalAlignment=VerticalAlignment.Top; value.Margin=new Thickness(0,5,5,5);
                    Grid.SetRow(value,row); Grid.SetColumn(value,i+1); value.ToolTip=Data.Text(metric,"condition","");
                    UI.Name(value,(i==0 ? "A " : "B ")+Data.Text(metric,"label","")+" "+value.Text+" "+unit); grid.Children.Add(value);
                }
                row++;
            }
            comparison.Children.Add(grid);
            foreach(object note in Data.Array(data,"summary_notes")) comparison.Children.Add(UI.Text(Convert.ToString(note),12,UI.Gold));
        }
        public void Render(Dictionary<string,object> d) {
            if(Data.Number(d,"draft_revision")<revision) return; rendering=true; try { revision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty"); calculated=Data.Flag(d,"calculated"); values=new Dictionary<string,object>(Data.Object(d,"raw"));
                var taskSource=Data.Object(d,"task_source"); origin.Text=Data.Text(taskSource,"brief","");
                origin.Foreground=Data.Flag(taskSource,"stale") ? UI.Gold : UI.Muted;
                origin.ToolTip=Data.Text(taskSource,"detail",""); origin.Visibility=origin.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                UI.Name(origin,"任务条件来源 · "+origin.Text); object[] specs=Data.Array(d,"fields"); bool first=fields.Children.Count==0; currentSpecs=specs; fields.Render(specs,values); mode.Visibility=specs.Length>0 ? Visibility.Visible : Visibility.Collapsed; if(first && specs.Length>0 && page!="equipment" && page!="alchemy") SetEditing(true); mode.Content=ModeLabel(); UI.Name(mode,Convert.ToString(mode.Content));
                RenderTaskContext(); taskContext.Visibility=specs.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                if(page=="equipment") { int desired=calculated ? 0 : 1; if(output.Children.IndexOf(comparison)!=desired) { output.Children.Remove(comparison); output.Children.Insert(desired,comparison); } }
                string text=Data.Text(d,"text",""); if(page=="alchemy" && !calculated && text=="填写条件后计算。") text=""; if(page=="inventory" && text.Length==0) text="选择物品后，可查看资料或加入比较 A / B。"; if(text!=articleText) { articleText=text; UI.IllustratedArticle(article,text,Data.Object(d,"artwork")); if(page=="equipment") RenderComparison(Data.Object(d,"comparison")); }
                if(page=="backups") {
                    var summary=Data.Object(d,"backup_summary"); backupSummary.Children.Clear();
                    string heading=Data.Text(summary,"heading",""), target=Data.Text(summary,"target",""), warning=Data.Text(summary,"warning","");
                    backupSummary.Visibility=heading.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                    article.Visibility=heading.Length>0 ? Visibility.Collapsed : Visibility.Visible;
                    if(heading.Length>0) {
                        var label=UI.Text(heading,13,UI.Muted); label.TextWrapping=TextWrapping.NoWrap; label.TextTrimming=TextTrimming.CharacterEllipsis; label.ToolTip=heading; System.Windows.Automation.AutomationProperties.SetHelpText(label,heading); backupSummary.Children.Add(label);
                        var progress=UI.Text(target,15); progress.Margin=new Thickness(0,2,0,4); backupSummary.Children.Add(progress);
                        if(warning.Length>0) backupSummary.Children.Add(UI.Text(warning,12,UI.Gold));
                    }
                }
                RenderResultDetails(Data.Array(d,"result_details"));
                map.Render(Data.Object(d,"map")); mapLegend.Visibility=mapDetails.Visibility=map.Visibility; mapCoordinates.Text=map.Description(); var rows=Data.Array(d,"rows"); string next=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(rows)+Data.Text(d,"selected",""); if(next!=rowSignature) { var priorRowFocus=Keyboard.FocusedElement; var previousRows=new Dictionary<string,Control>(rowControls); rowControls.Clear(); selector.Children.Clear(); foreach(object item in rows) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""), token=Data.Text(row,"token",""); var button=UI.Button("",delegate { if(!host.Frozen) { host.Send("game_select","page",page,"id",id,"token",token); selection.IsExpanded=false; } }); string caption=Data.Text(row,"summary",Data.Text(row,"text","")); button.Content=UI.ImageRow(caption,Data.Object(row,"artwork")); UI.Name(button,caption); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; button.Margin=new Thickness(0); button.Padding=new Thickness(2,6,4,6); button.Background=id==Data.Text(d,"selected","") ? UI.Panel : Brushes.Transparent; button.BorderBrush=UI.Line; button.BorderThickness=new Thickness(0,0,0,1); selector.Children.Add(button); rowControls[id]=button; } host.Manager.RebindTaskFocus(page,previousRows,rowControls,this,priorRowFocus); rowSignature=next; } selection.Visibility=rows.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                notice.Text=Data.Text(d,"notice",""); if(notice.Text.Length==0 && Dirty && specs.Length>0) notice.Text=calculated ? "有未保存的修改" : "条件已修改，待重新计算"; notice.Visibility=notice.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed; if(receipt!=null) { receipt.Visibility=receiptBrief.Visibility=notice.Visibility; receiptBrief.Text=Data.Text(d,"notice_brief","操作回执"); }
                string nextActions=new JavaScriptSerializer().Serialize(Data.Array(d,"actions"))+"/"+(Data.Text(d,"selected","").Length>0);
                if(nextActions!=actionSignature) { var priorFocus=Keyboard.FocusedElement; var previousControls=new Dictionary<string,Control>(actionControls); actions.Children.Clear(); actionControls.Clear(); var extras=new List<MenuItem>(); Button more=null;
                string primaryCommand=page=="inventory" ? "reference" : page=="backups" ? "backup_preview" : page=="map" ? "map_known" : "calculate";
                if(page=="backups") foreach(object item in Data.Array(d,"actions")) if(Data.Text((Dictionary<string,object>)item,"id","")=="backup_confirm") primaryCommand="backup_confirm";
                var orderedActions=new List<object>(Data.Array(d,"actions"));
                if(page=="alchemy") { orderedActions.Clear(); foreach(string id in new[]{"calculate","import","add_target","undo","save","update"}) foreach(object item in Data.Array(d,"actions")) if(Data.Text((Dictionary<string,object>)item,"id","")==id) orderedActions.Add(item); foreach(object item in Data.Array(d,"actions")) { string id=Data.Text((Dictionary<string,object>)item,"id",""); if(id!="calculate" && id!="import" && id!="add_target" && id!="undo" && id!="save" && id!="update") orderedActions.Add(item); } }
                foreach(object item in orderedActions) {
                    var action=(Dictionary<string,object>)item; string command=Data.Text(action,"id","");
                    Action clicked=delegate { if(host.Frozen) return; if(page=="alchemy" && (command=="add_target" || command=="add_resource" || command=="add_path")) { string count=command=="add_target" ? "targets" : command=="add_resource" ? "resources" : "paths"; int index; Int32.TryParse(Data.Text(Raw(),count,"0"),out index); pendingEditorSection=(command=="add_target" ? "产出目标 " : command=="add_resource" ? "独立库存 " : "明确指定前置生产路径 ")+(index+1)+(command=="add_target" || command=="add_resource" ? " ·" : ""); } Flush(); host.Send("game_action","page",page,"command",command=="save" ? "name_plan" : command,"values",Raw(),"draft_revision",revision); };
                    string label=Data.Text(action,"text",""), reason=Data.Text(action,"reason",""); bool disabled=Data.Flag(action,"disabled");
                    bool direct=command==primaryCommand || page=="inventory" && (command=="equip_a" || command=="equip_b") || page=="alchemy" && command=="add_target";
                    if(page=="alchemy" && command=="import") label="带入已知库存";
                    if(command=="calculate" && page=="equipment") label="比较装备";
                    if(command=="calculate" && page=="alchemy") label="计算";
                    if(command=="undo" && (page=="equipment" || page=="alchemy")) label="撤回带入";
                    if(direct) { var button=UI.Button(label,clicked,command==primaryCommand); button.Padding=new Thickness(10,6,10,6); button.MinHeight=30; button.IsEnabled=!disabled; string help=reason.Length>0 ? reason : command=="import" && page=="alchemy" ? "主动替换当前库存与能量；保留目标。未知身份与未确认状态不猜测，可撤回。" : ""; if(help.Length>0) { button.ToolTip=help; System.Windows.Controls.ToolTipService.SetShowOnDisabled(button,true); System.Windows.Automation.AutomationProperties.SetHelpText(button,help); } actions.Children.Add(button); actionControls[command]=button; }
                    else if(!(page=="inventory" && Data.Text(d,"selected","").Length==0)) { var menuItem=UI.Item(label,clicked,!disabled); if(reason.Length>0) { menuItem.ToolTip=reason; System.Windows.Controls.ToolTipService.SetShowOnDisabled(menuItem,true); System.Windows.Automation.AutomationProperties.SetHelpText(menuItem,reason); } extras.Add(menuItem); actionControls[command]=menuItem; }
                }
                if(extras.Count>0) { string extraLabel=page=="alchemy" ? "计划操作" : page=="inventory" ? "鉴定详情" : "更多操作"; more=UI.Button(extraLabel,delegate { UI.Menu(more,extras.ToArray()); }); if(page=="alchemy") { more.Padding=new Thickness(10,6,10,6); more.MinHeight=30; more.ToolTip="移除目标、增减独立库存与前置路径"; } actions.Children.Add(more); actionControls["__more"]=more; }
                host.Manager.RebindTaskFocus(page,previousControls,actionControls,this,priorFocus); actionSignature=nextActions; }
                if(Data.Flag(d,"focus_result")) { SetEditing(false); scroll.ScrollToTop(); }
                if(pendingEditorSection.Length>0) { string section=pendingEditorSection; foreach(UIElement child in fields.Children) { var group=child as Expander; if(group!=null && System.Windows.Automation.AutomationProperties.GetName(group).StartsWith(section)) { pendingEditorSection=""; OpenEditor(section); break; } } }
            } finally { rendering=false; }
        }
    }

    sealed class LookupForm : Grid {
        readonly Helper Host;
        readonly TextBox search=UI.Edit("搜索物品、敌人或技能",200), note=UI.Edit("用户用途或假设备注",1200);
        readonly TextBlock searchHint=UI.Text("搜索名称、别名或用途",13,UI.Muted);
        readonly Button clearSearch;
        readonly ComboBox category=UI.Combo("图鉴分类");
        readonly TextBlock listing=UI.Text("",12,UI.Muted);
        readonly FieldEditor fields=new FieldEditor();
        readonly StackPanel article=new StackPanel(), candidates=new StackPanel(), parameterBody=new StackPanel();
        readonly StackPanel searchHeader=new StackPanel();
        readonly DockPanel readingHeader=new DockPanel();
        readonly WrapPanel bottom=new WrapPanel();
        readonly ScrollViewer scroll;
        readonly TextBlock feedback=UI.Text("",13,UI.Gold);
        readonly Button back, primary, saveCalculation, more, moreResults, previousResults, pinned;
        readonly WrapPanel resultPages;
        readonly TextBlock scopeSource=UI.Text("",12,UI.Muted);
        readonly List<Button> resultButtons=new List<Button>();
        readonly Dictionary<string,double> positions=new Dictionary<string,double>();
        readonly Dictionary<string,bool> openedSections=new Dictionary<string,bool>();
        readonly Dictionary<string,Expander> articleSections=new Dictionary<string,Expander>();
        readonly Dictionary<string,Control> articleLinks=new Dictionary<string,Control>();
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
            search.ToolTip="搜索名称、别名或用途 · ↓进入结果 · Enter打开首项；近似建议需选择";
            var searchLine=new Grid { Margin=new Thickness(0,0,0,8) };
            search.Padding=new Thickness(10,3,38,3); search.Height=38; searchLine.Children.Add(search);
            searchHint.IsHitTestVisible=false; searchHint.VerticalAlignment=VerticalAlignment.Center; searchHint.Margin=new Thickness(12,0,42,0); searchHint.TextWrapping=TextWrapping.NoWrap; searchHint.TextTrimming=TextTrimming.CharacterEllipsis; searchLine.Children.Add(searchHint);
            clearSearch=UI.Button("×",delegate { if(!Host.Frozen) { search.Clear(); search.Focus(); } }); UI.Name(clearSearch,"清空搜索"); clearSearch.ToolTip="清空搜索";
            clearSearch.FontSize=20; clearSearch.Width=30; clearSearch.MinHeight=30; clearSearch.Height=30; clearSearch.Padding=new Thickness(0); clearSearch.Margin=new Thickness(0,0,5,0); clearSearch.HorizontalAlignment=HorizontalAlignment.Right; clearSearch.VerticalAlignment=VerticalAlignment.Center; clearSearch.Background=Brushes.Transparent; clearSearch.BorderThickness=new Thickness(0); clearSearch.Visibility=Visibility.Collapsed; searchLine.Children.Add(clearSearch);
            searchHeader.Children.Add(searchLine);
            var browseLine=new DockPanel { Margin=new Thickness(0,0,0,8) };
            category.MinHeight=30; category.MinWidth=135; category.MaxWidth=210;
            category.SelectionChanged+=delegate { if(!rendering && !Host.Frozen && category.SelectedItem!=null) Host.Send("browse","surface","lookup","category",Convert.ToString(category.SelectedItem)); };
            DockPanel.SetDock(category,Dock.Left); browseLine.Children.Add(category);
            var all=UI.Button("全部",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("browse","surface","lookup","category","全部"); search.Focus(); } });
            all.Background=Brushes.Transparent; all.Padding=new Thickness(10,4,10,4); all.Margin=new Thickness(6,0,0,0); UI.Name(all,"浏览全部图鉴"); DockPanel.SetDock(all,Dock.Right); browseLine.Children.Add(all);
            listing.HorizontalAlignment=HorizontalAlignment.Right; listing.VerticalAlignment=VerticalAlignment.Center; listing.Margin=new Thickness(10,0,0,0); browseLine.Children.Add(listing); searchHeader.Children.Add(browseLine);
            scopeSource.Margin=new Thickness(0,0,0,6); scopeSource.Visibility=Visibility.Collapsed; searchHeader.Children.Add(scopeSource);
            pinned=UI.Button("查看固定参考 ›",delegate { FlushEdit(); Host.Send("view_pin","surface","lookup"); }); pinned.Visibility=Visibility.Collapsed; pinned.HorizontalAlignment=HorizontalAlignment.Left; searchHeader.Children.Add(pinned);
            Children.Add(searchHeader);
            back=UI.Button("‹ 图鉴",delegate { if(mode=="edit") SetMode("result"); else { SetMode("search"); search.Focus(); } });
            more=UI.Button("···",ShowActions); UI.Name(more,"条目操作"); more.ToolTip="收藏、保存与参考来源"; more.MinWidth=34; more.FontSize=18;
            foreach(var button in new[]{back,more}) { button.MinHeight=28; button.Padding=new Thickness(8,3,8,3); button.Margin=new Thickness(0,0,6,4); }
            back.Background=more.Background=Brushes.Transparent; back.HorizontalAlignment=HorizontalAlignment.Left;
            DockPanel.SetDock(more,Dock.Right); readingHeader.Children.Add(more); readingHeader.Children.Add(back); readingHeader.Visibility=Visibility.Collapsed; Children.Add(readingHeader);
            moreResults=UI.Button("浏览全部资料",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("more","surface","lookup"); } });
            previousResults=UI.Button("上一页",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("previous_results","surface","lookup"); } });
            resultPages=UI.Buttons(previousResults,moreResults);
            scroll=UI.Scroll(candidates); Grid.SetRow(scroll,1); Children.Add(scroll);
            primary=UI.Button("调整条件",delegate { if(mode=="edit") Calculate(); else { SetMode("edit"); fields.MoveFocus(new TraversalRequest(FocusNavigationDirection.First)); } },true);
            saveCalculation=UI.Button("保存这次计算…",delegate { FlushEdit(); Host.Send("save_plan","surface","lookup"); });
            bottom.Children.Add(primary); bottom.Children.Add(saveCalculation); bottom.Margin=new Thickness(0,8,0,0); var footer=UI.Stack(feedback,bottom); Grid.SetRow(footer,2); Children.Add(footer); bottom.Visibility=Visibility.Collapsed; feedback.Visibility=Visibility.Collapsed;
            fields.Submit=Calculate; fields.Changed=delegate { Edited(); };
            note.AcceptsReturn=true; note.MinHeight=80; note.TextWrapping=TextWrapping.Wrap; note.TextChanged+=delegate { Edited(false); };
            parameterBody.Children.Add(fields);
            parameterBody.Children.Add(UI.Section("用途与假设备注",UI.Field("备注（可选，未验证）",note),false));
            search.TextChanged+=delegate { searchHint.Visibility=search.Text.Length==0 ? Visibility.Visible : Visibility.Collapsed; clearSearch.Visibility=search.Text.Length==0 ? Visibility.Collapsed : Visibility.Visible; if(!rendering && !Host.Frozen) Host.Send("query","surface","lookup","text",search.Text); };
            search.KeyDown+=delegate(object sender,KeyEventArgs e) {
                if(e.Key==Key.Enter) { Host.Send("first","surface","lookup"); e.Handled=true; }
                else if(e.Key==Key.Down && resultButtons.Count>0) { resultButtons[0].Focus(); e.Handled=true; }
            };
        }
        void SetMode(string next) {
            if(next==mode) return;
            positions[mode]=scroll.VerticalOffset; mode=next; back.Content=mode=="edit" ? "‹ 结果" : "‹ 图鉴"; UI.Name(back,Convert.ToString(back.Content));
            searchHeader.Visibility=mode=="search" ? Visibility.Visible : Visibility.Collapsed;
            readingHeader.Visibility=mode=="search" ? Visibility.Collapsed : Visibility.Visible;
            scroll.Content=mode=="search" ? (object)candidates : mode=="edit" ? (object)parameterBody : article;
            UpdateActions(); double position; scroll.ScrollToVerticalOffset(positions.TryGetValue(mode,out position) ? position : 0); UI.Fade(scroll);
        }
        void UpdateActions() {
            bool busy=Data.Flag(state,"calculating");
            feedback.Text=mode=="search" ? Data.Text(state,"search_error","") : Data.Text(state,"parameter_error",busy ? "正在计算…" : "");
            if(mode!="search" && feedback.Text.Length==0 && busy) feedback.Text="正在计算…";
            if(mode!="search" && feedback.Text.Length==0) feedback.Text=Data.Text(state,"operation_receipt","");
            feedback.ToolTip=feedback.Text; System.Windows.Automation.AutomationProperties.SetHelpText(feedback,feedback.Text);
            if(mode!="search" && feedback.Text==Data.Text(state,"operation_receipt","")) {
                string brief=Data.Text(state,"operation_brief",""); if(brief.Length>0) feedback.Text=brief;
            }
            feedback.Visibility=feedback.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
            bool hasEntry=Data.Text(state,"entry_id","").Length>0;
            bool custom=Data.Flag(state,"can_save") && Dirty;
            bottom.Visibility=hasEntry && mode!="search" && (Data.Array(state,"fields").Length>0 || custom) ? Visibility.Visible : Visibility.Collapsed;
            saveCalculation.Visibility=custom && mode=="result" ? Visibility.Visible : Visibility.Collapsed;
            primary.Visibility=Data.Array(state,"fields").Length>0 ? Visibility.Visible : Visibility.Collapsed;
            primary.IsEnabled=!busy; primary.Content=busy ? "正在计算…" : mode=="edit" ? "重新计算" : Data.Flag(state,"needs_calculation") ? "补全条件" : "按我的情况计算"; UI.Name(primary,Convert.ToString(primary.Content));
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
        void AddResultButton(Button button,int index) {
            button.KeyDown+=delegate(object sender,KeyEventArgs e) { if(e.Key==Key.Down && index+1<resultButtons.Count) { resultButtons[index+1].Focus(); e.Handled=true; } else if(e.Key==Key.Up) { if(index>0) resultButtons[index-1].Focus(); else search.Focus(); e.Handled=true; } };
            resultButtons.Add(button); candidates.Children.Add(button);
        }
        void ShowActions() {
            bool valid=Data.Flag(state,"can_save"), hasEntry=Data.Text(state,"entry_id","").Length>0;
            var items=new List<object>();
            foreach(string[] pair in new[]{new[]{"带入最新已知角色条件","use_latest"},new[]{"撤回本次条件带入","undo_import"},new[]{"","separator"},new[]{Data.Flag(state,"has_saved_plan") ? "更新或另存方案…" : "保存方案…","save_plan"},new[]{"重新读取当前方案","reload_plan"},new[]{"我的方案…","choose_plan"},new[]{"","separator"},new[]{"查看固定参考","view_pin"},new[]{"清除固定参考","clear_pin"}}) {
                string action=pair[1]; bool enabled=action=="view_pin" || action=="clear_pin" ? Data.Flag(state,"has_pin") : action=="undo_import" ? Data.Flag(state,"undo") : action=="use_latest" ? Data.Flag(state,"can_latest") : action=="save_plan" || action=="pin" ? valid : action=="favorite" || action=="provenance" ? hasEntry : action=="reload_plan" ? Data.Flag(state,"has_saved_plan") : true;
                if(action=="separator") { items.Add(new Separator()); continue; }
                var item=UI.Item(pair[0],delegate { FlushEdit(); if(action=="choose_plan") Host.Manager.OpenPage("plans"); else Host.Send(action,"surface","lookup"); },enabled);
                if(!enabled) {
                    string reason=action=="undo_import" ? "尚无可撤回的条件带入" : action=="reload_plan" ? "先打开一个已保存方案" : action=="view_pin" || action=="clear_pin" ? "先在数值条目点击「固定」" : action=="use_latest" ? "当前没有可带入的已知角色条件" : Data.Flag(state,"needs_calculation") ? "先重新计算有效条件" : "当前没有可保存的有效数值条件";
                    item.ToolTip=reason; System.Windows.Controls.ToolTipService.SetShowOnDisabled(item,true); System.Windows.Automation.AutomationProperties.SetHelpText(item,reason);
                }
                items.Add(item);
            }
            items.Add(UI.Item("方案与收藏（完整面板）",delegate { Host.Send("panel","page","workspace"); })); UI.Menu(more,items.ToArray());
        }
        static Grid LabeledValues(object[] values) {
            var grid=new Grid { Margin=new Thickness(0,4,0,8) }; grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1.05,GridUnitType.Star) }); int index=0;
            foreach(object raw in values) {
                var value=raw as Dictionary<string,object>; if(value==null) continue; grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
                var label=UI.Text(Data.Text(value,"label",""),14,UI.Muted); label.Margin=new Thickness(0,5,10,5); Grid.SetRow(label,index); grid.Children.Add(label);
                string unit=Data.Text(value,"unit",""); var number=UI.Text(Data.Text(value,"value","?")+(unit.Length>0 ? " "+unit : ""),14); number.FontWeight=FontWeights.SemiBold;
                var body=UI.Stack(number); string condition=Data.Text(value,"condition",""); if(condition.Length>0) body.Children.Add(UI.Text(condition,13,UI.Muted));
                body.Margin=new Thickness(0,4,0,6); Grid.SetRow(body,index++); Grid.SetColumn(body,1); grid.Children.Add(body);
            } return grid;
        }
        Expander RememberSection(string identity,string title,UIElement body,bool initial) {
            bool open; if(!openedSections.TryGetValue(identity,out open)) open=initial; var section=UI.Section(title,body,open);
            section.Expanded+=delegate { openedSections[identity]=true; }; section.Collapsed+=delegate { openedSections[identity]=false; }; articleSections[identity]=section; return section;
        }
        Dictionary<string,Control> ArticleTargets(bool existingHeaders) {
            var targets=new Dictionary<string,Control>(articleLinks);
            foreach(var pair in articleSections) { if(!existingHeaders) targets[pair.Key]=pair.Value; else if(pair.Value.Template!=null && VisualTreeHelper.GetChildrenCount(pair.Value)>0) { var title=pair.Value.Template.FindName("title",pair.Value) as Control; if(title!=null) targets[pair.Key]=title; } }
            return targets;
        }
        void RenderArticle(Dictionary<string,object> data) {
            string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(Data.Map("entry",Data.Text(data,"entry_id",""),"notice",Data.Text(data,"primary_notice",""),"brief",Data.Text(data,"primary_brief",""),"sections",Data.Array(data,"numeric_sections"),"summary",Data.Array(data,"primary_values"),"note",Data.Text(data,"primary_note",""),"reading_notes",Data.Array(data,"reading_notes"),"recipes",Data.Array(data,"recipes"),"text",Data.Text(data,"result",""),"origin",Data.Text(data,"origin_brief",""),"status",Data.Text(data,"status",""),"favorite",Data.Flag(data,"favorite"),"can_save",Data.Flag(data,"can_save"),"description",Data.Text(data,"description",""),"related",Data.Array(data,"related")));
            if(signature==articleSignature) return;
            var priorFocus=Keyboard.FocusedElement; var previous=ArticleTargets(true); articleSections.Clear(); articleLinks.Clear(); articleSignature=signature; article.Children.Clear();
            string identity=Data.Text(data,"entry_id",""), name=Data.Text(data,"entry_name","");
            if(identity.Length==0) return;
            object[] sections=Data.Array(data,"numeric_sections"), main=Data.Array(data,"primary_values"), readingNotes=Data.Array(data,"reading_notes");
            var secondary=new StackPanel(); var primaryBody=readingNotes.Length>0 ? secondary : article;
            string primaryBrief=Data.Text(data,"primary_brief","");
            bool compactResult=main.Length==2 && (identity.StartsWith("actors.hero.spells.") || primaryBrief.Length>0);
            bool compactHealing=main.Length==2 && primaryBrief.Length>0;
            var title=new DockPanel { Margin=compactResult ? new Thickness(0,0,0,2) : new Thickness(0,4,0,12) };
            var pin=UI.Button("固定",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("pin","surface","lookup"); } });
            pin.IsEnabled=Data.Flag(data,"can_save"); pin.ToolTip=pin.IsEnabled ? "固定到随行 · 保留本次条件" : Data.Flag(data,"needs_calculation") ? "先重新计算有效条件" : "当前没有可固定的有效数值条件";
            System.Windows.Controls.ToolTipService.SetShowOnDisabled(pin,true); System.Windows.Automation.AutomationProperties.SetHelpText(pin,Convert.ToString(pin.ToolTip)); UI.Name(pin,"固定到随行"); pin.Padding=new Thickness(6,2,6,2); pin.Margin=new Thickness(0); pin.Background=Brushes.Transparent; DockPanel.SetDock(pin,Dock.Right); title.Children.Add(pin); articleLinks[identity+"/pin"]=pin;
            var favorite=UI.Button(Data.Flag(data,"favorite") ? "★" : "☆",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("favorite","surface","lookup"); } });
            favorite.FontSize=22; favorite.Padding=new Thickness(6,0,6,0); favorite.Background=Brushes.Transparent; favorite.Foreground=UI.Gold; favorite.ToolTip=Data.Flag(data,"favorite") ? "取消收藏" : "收藏"; UI.Name(favorite,Convert.ToString(favorite.ToolTip));
            if(compactResult) favorite.Margin=new Thickness(0);
            DockPanel.SetDock(favorite,Dock.Right); title.Children.Add(favorite); articleLinks[identity+"/favorite"]=favorite;
            var picture=UI.Artwork(Data.Object(data,"artwork"),compactResult ? 28 : 38); DockPanel.SetDock(picture,Dock.Left); title.Children.Add(picture);
            var nameText=UI.Text(name,compactResult ? 18 : 19); nameText.FontWeight=FontWeights.SemiBold;
            var headingText=UI.Stack(nameText); headingText.VerticalAlignment=VerticalAlignment.Center;
            string variant=Data.Text(data,"entry_hint",""); if(variant.Length>0 && !(compactResult && variant=="法术")) headingText.Children.Add(UI.Text(variant,13,UI.Muted));
            string imageCaption=Data.Text(Data.Object(data,"artwork"),"caption","");
            title.Children.Add(headingText); article.Children.Add(title);
            string prerequisite=Data.Text(data,"primary_notice","");
            if(prerequisite.Length>0) { var notice=UI.Text(prerequisite,13,UI.Gold); notice.Margin=new Thickness(0,0,0,compactResult ? 4 : 8); article.Children.Add(notice); }
            if(primaryBrief.Length>0) { var basis=UI.Text(primaryBrief,13,UI.Gold); article.Children.Add(basis); }
            string introduction=Data.Text(data,"introduction","");
            string origin=Data.Text(data,"origin_brief","");
            bool conditioned=Data.Array(data,"fields").Length>0;
            bool caution=origin.StartsWith("旧") || origin.StartsWith("条件") || origin.StartsWith("需要") || origin.StartsWith("参考来源") || origin.StartsWith("种植");
            foreach(object raw in readingNotes) { string text=Convert.ToString(raw); if(text.Length==0) continue; var mechanism=UI.Text(text,15); mechanism.Margin=new Thickness(0,0,0,8); article.Children.Add(mechanism); }
            var primaryKeys=new HashSet<string>(); var notes=new HashSet<string>();
            var metrics=new UniformGrid { Columns=main.Length, Margin=new Thickness(0,2,0,compactResult ? 4 : 10) };
            foreach(object raw in main) {
                var value=(Dictionary<string,object>)raw; string label=Data.Text(value,"label",""), number=Data.Text(value,"value","?"), unit=Data.Text(value,"unit","");
                primaryKeys.Add(label+"|"+number+"|"+unit);
                if(main.Length==3 || compactResult) {
                    var labelText=UI.Text(label,compactResult ? 12 : 13,UI.Muted);
                    var numberText=UI.Text(number+(unit.Length>0 ? " "+unit : ""),compactResult ? 16 : 17); numberText.FontWeight=FontWeights.SemiBold;
                    if(compactHealing) {
                        var cell=UI.Text("",12,UI.Muted); cell.Inlines.Add(new System.Windows.Documents.Run(label+" "));
                        cell.Inlines.Add(new System.Windows.Documents.Run(number+(unit.Length>0 ? " "+unit : "")) { FontSize=16,FontWeight=FontWeights.SemiBold,Foreground=UI.Ink });
                        UI.Name(cell,label+" "+number+(unit.Length>0 ? " "+unit : ""));
                        metrics.Children.Add(cell);
                    } else metrics.Children.Add(UI.Stack(labelText,numberText));
                } else {
                var line=new DockPanel { Margin=new Thickness(0,0,0,5) };
                var metric=UI.Text(number+(unit.Length>0 ? " "+unit : ""),18); metric.FontWeight=FontWeights.SemiBold; DockPanel.SetDock(metric,Dock.Right); line.Children.Add(metric);
                var caption=UI.Text(label,14); caption.VerticalAlignment=VerticalAlignment.Center; caption.Margin=new Thickness(0,0,12,0); line.Children.Add(caption); primaryBody.Children.Add(line);
                }
                string noteText=Data.Text(value,"condition",""); if(noteText.Length>0) notes.Add(noteText);
            }
            if(main.Length==3 || compactResult) primaryBody.Children.Add(metrics);
            string primaryNote=Data.Text(data,"primary_note",""); if(primaryNote.Length>0) { if(primaryBrief.Length>0) secondary.Children.Add(UI.Text(primaryNote,14,UI.Gold)); else notes.Add(primaryNote); }
            foreach(string noteText in notes) { var noteLine=UI.Text(noteText,14,UI.Gold); noteLine.Margin=new Thickness(0,2,0,8); article.Children.Add(noteLine); }
            if(caution || conditioned) { var context=UI.Text(origin,13,caution ? UI.Gold : UI.Muted); context.Margin=new Thickness(0,0,0,8); article.Children.Add(context); }
            if(introduction.Length>0 && !Array.Exists(readingNotes,delegate(object value) { return Convert.ToString(value)==introduction; })) { var purpose=UI.Text(introduction,14,UI.Muted); purpose.Margin=new Thickness(0,0,0,8); (readingNotes.Length>0 || main.Length>0 ? secondary : article).Children.Add(purpose); }
            if(imageCaption.Length>0 && imageCaption!="游戏原始图像") { var caption=UI.Text(imageCaption,13,UI.Muted); caption.Margin=new Thickness(0,0,0,8); article.Children.Add(caption); }
            foreach(object raw in Data.Array(data,"recipes")) {
                var recipe=raw as Dictionary<string,object>; if(recipe==null) continue;
                string recipeId=Data.Text(recipe,"id",""), recipeToken=Data.Text(recipe,"token",""), recipeName=Data.Text(recipe,"name",name);
                var add=UI.Button("加入炼金目标",delegate { if(!Host.Frozen) { FlushEdit(); Host.Send("alchemy_recipe","surface","lookup","recipe",recipeId,"token",recipeToken); } },true);
                if(Data.Array(data,"recipes").Length>1 || recipeName!=name) { var recipeHeading=UI.Text(recipeName,14); recipeHeading.Margin=new Thickness(0,6,0,2); article.Children.Add(recipeHeading); }
                add.HorizontalAlignment=HorizontalAlignment.Left; add.ToolTip="将"+recipeName+"加入现有炼金计划"; UI.Name(add,"加入炼金目标 · "+recipeName); article.Children.Add(add); articleLinks[identity+"/recipe/"+recipeId]=add;
            }
            string description=Data.Text(data,"description","");
            if(description.Length>0 && description!=introduction) {
                string remainder=description.StartsWith(introduction) ? description.Substring(introduction.Length).Trim() : description;
                var explanation=UI.Text(remainder,14); explanation.Margin=new Thickness(0,0,0,12); secondary.Children.Add(explanation);
            }
            if(sections.Length==0) { var text=new StackPanel(); UI.Article(text,Data.Text(data,"result","")); secondary.Children.Add(text); }
            foreach(object raw in sections) {
                var section=raw as Dictionary<string,object>; if(section==null) continue;
                string sectionTitle=Data.Text(section,"title","数值"); object[] columns=Data.Array(section,"columns"), rows=Data.Array(section,"rows");
                var values=new List<object>();
                foreach(string field in new[]{"values","selected_values"}) foreach(object item in Data.Array(section,field)) {
                    var value=(Dictionary<string,object>)item;
                    if(!primaryKeys.Contains(Data.Text(value,"label","")+"|"+Data.Text(value,"value","")+"|"+Data.Text(value,"unit",""))) values.Add(item);
                }
                if(values.Count>0) { var subtitle=UI.Text(sectionTitle,14); subtitle.FontWeight=FontWeights.SemiBold; subtitle.Margin=new Thickness(0,8,0,4); secondary.Children.Add(subtitle); secondary.Children.Add(LabeledValues(values.ToArray())); }
                if(columns.Length>0 && rows.Length>0) {
                    var table=new StackPanel(); int rowIndex=0;
                    foreach(object rawRow in rows) {
                        var cells=rawRow as object[]; if(cells==null) continue; var labeled=new List<object>();
                        for(int i=1;i<Math.Min(columns.Length,cells.Length);i++) labeled.Add(Data.Map("label",Convert.ToString(columns[i]),"value",Convert.ToString(cells[i])));
                        string rowTitle=Convert.ToString(columns[0])+" "+(cells.Length>0 ? Convert.ToString(cells[0]) : "");
                        bool current=section.ContainsKey("selected_row") && section["selected_row"]!=null && Data.Number(section,"selected_row")==rowIndex++;
                        if(current) rowTitle+=" · 当前条件";
                        var rowHeading=UI.Text(rowTitle,14,current ? UI.Gold : UI.Ink); rowHeading.FontWeight=FontWeights.SemiBold; rowHeading.Margin=new Thickness(0,12,0,0); table.Children.Add(rowHeading); table.Children.Add(LabeledValues(labeled.ToArray()));
                    }
                    secondary.Children.Add(UI.Text(sectionTitle,14,UI.Gold)); secondary.Children.Add(table);
                }
                string noteText=Data.Text(section,"note",""); if(noteText.Length>0 && !notes.Contains(noteText)) { var explanation=UI.Text(noteText,13,UI.Muted); explanation.Margin=new Thickness(0,4,0,10); secondary.Children.Add(explanation); }
            }
            var provenance=new StackPanel();
            if(!caution && !conditioned) provenance.Children.Add(UI.Text("官方资料 · "+Data.Text(data,"reference_version",""),13,UI.Muted));
            string prose=Data.Text(data,"result_prose",""); UI.Article(provenance,prose+"\n\n"+Data.Text(data,"status",""));
            int sourceIndex=0; string token=Data.Text(data,"sources_token","");
            foreach(object raw in Data.Array(data,"sources")) { var link=(Dictionary<string,object>)raw; int index=sourceIndex++; var sourceButton=UI.Button(Data.Text(link,"label","官方源码"),delegate { Host.Send("source_link","surface","lookup","index",index,"token",token); }); provenance.Children.Add(sourceButton); articleLinks[identity+"/source/"+Data.Text(link,"url",Convert.ToString(index))]=sourceButton; }
            if(secondary.Children.Count>0) article.Children.Add(RememberSection(identity+"/details","详情",secondary,main.Length==0 && description.Length==0));
            int relatedIndex=0;
            foreach(object raw in Data.Array(data,"related")) {
                var row=(Dictionary<string,object>)raw; int index=relatedIndex++; string relatedToken=Data.Text(row,"token","");
                var link=UI.Button(Data.Text(row,"text","")+" ›",delegate { FlushEdit(); Host.Send("related","surface","lookup","index",index,"token",relatedToken); });
                link.HorizontalAlignment=HorizontalAlignment.Left; article.Children.Add(link); articleLinks[identity+"/related/"+index]=link;
            }
            article.Children.Add(RememberSection(identity+"/provenance","条件与来源",provenance,false));
            Host.Manager.RebindTaskFocus("lookup",previous,ArticleTargets(false),mode=="search" ? (UIElement)search : back,priorFocus);
        }
        public void Render(Dictionary<string,object> d) {
            if(Data.Number(d,"draft_revision")<draftRevision) return;
            rendering=true; try {
                state=d;
                string choices=String.Join("|",Array.ConvertAll(Data.Array(d,"categories"),delegate(object value) { return Convert.ToString(value); }));
                if(!Object.Equals(category.Tag,choices)) { category.Items.Clear(); foreach(object value in Data.Array(d,"categories")) category.Items.Add(Convert.ToString(value)); category.Tag=choices; }
                category.SelectedItem=Data.Text(d,"category","常用");
                long total=Data.Number(d,"total_count"), shown=Data.Number(d,"shown_count"), offset=Data.Number(d,"page_offset");
                listing.Text=Data.Flag(d,"suggested") ? "" : total>shown ? (shown>0 ? (offset+1)+"–"+(offset+shown)+" / "+total : "0 / "+total) : total+" 项";
                scopeSource.Text=Data.Text(d,"scope_source",""); scopeSource.Visibility=scopeSource.Text.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                moreResults.Content=Data.Flag(d,"suggested") ? "浏览全部资料" : "下一页";
                UI.Name(moreResults,Convert.ToString(moreResults.Content));
                moreResults.Visibility=Data.Flag(d,"can_more") ? Visibility.Visible : Visibility.Collapsed;
                previousResults.Visibility=Data.Flag(d,"can_previous") ? Visibility.Visible : Visibility.Collapsed;
                draftRevision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty"); pinned.Visibility=Data.Flag(d,"has_pin") ? Visibility.Visible : Visibility.Collapsed;
                if(!search.IsKeyboardFocused) UI.Replace(search,Data.Text(d,"query",""));
                var rows=Data.Array(d,"rows"); var suggestions=Data.Array(d,"suggestions"); var serializer=new JavaScriptSerializer { MaxJsonLength=524288 }; string signature=serializer.Serialize(rows)+serializer.Serialize(suggestions)+Data.Flag(d,"can_more")+Data.Flag(d,"can_previous")+offset;
                if(signature!=rowsSignature) {
                    int focused=resultButtons.FindIndex(delegate(Button b) { return b.IsKeyboardFocusWithin; }); candidates.Children.Clear(); resultButtons.Clear(); string group="";
                    foreach(object item in rows) {
                        var row=(Dictionary<string,object>)item; int index=resultButtons.Count; string token=Data.Text(row,"token","");
                        var button=UI.Button("",delegate { if(!Host.Frozen) Host.Send("select","surface","lookup","index",index,"token",token); });
                        string text=Data.Text(row,"text",""); string nextGroup=Data.Text(row,"group","");
                        if(nextGroup.Length>0 && nextGroup!=group) { var label=UI.Text(nextGroup,12,UI.Muted); label.Margin=new Thickness(2,10,0,4); candidates.Children.Add(label); group=nextGroup; }
                        button.Content=UI.ReferenceRow(Data.Text(row,"name",text),Data.Text(row,"hint",""),Data.Object(row,"artwork"));
                        UI.Name(button,text); button.ToolTip=Data.Text(row,"context",""); button.HorizontalContentAlignment=HorizontalAlignment.Stretch;
                        button.Background=Brushes.Transparent; button.BorderBrush=UI.Line; button.BorderThickness=new Thickness(0,0,0,1); button.Padding=new Thickness(2,6,6,6); button.Margin=new Thickness(0);
                        AddResultButton(button,index);
                    }
                    if(rows.Length==0 && suggestions.Length>0) {
                        var prompt=UI.Text("是否要找",13,UI.Muted); prompt.Margin=new Thickness(0,0,0,6); candidates.Children.Add(prompt);
                        foreach(object item in suggestions) {
                            var row=(Dictionary<string,object>)item; int index=resultButtons.Count; string token=Data.Text(row,"token","");
                            var button=UI.Button("",delegate { if(!Host.Frozen) Host.Send("suggestion","surface","lookup","index",index,"token",token); });
                            string text=Data.Text(row,"text",""); button.Content=UI.ImageRow(text,Data.Object(row,"artwork")); UI.Name(button,"近似建议 · "+text); button.HorizontalContentAlignment=HorizontalAlignment.Stretch;
                            AddResultButton(button,index);
                        }
                    } else if(rows.Length==0) candidates.Children.Add(UI.Text("没有匹配条目，可清空搜索或切换分类。",13,UI.Muted));
                    if(Data.Flag(d,"can_more") || Data.Flag(d,"can_previous")) candidates.Children.Add(resultPages);
                    if(focused>=0 && focused<resultButtons.Count && mode=="search") resultButtons[focused].Focus(); rowsSignature=signature;
                }
                object[] specs=Data.Array(d,"fields"); var rawValues=new Dictionary<string,object>();
                foreach(object item in specs) { var spec=(Dictionary<string,object>)item; rawValues[Data.Text(spec,"key","")]=Data.Text(spec,"raw",""); }
                fields.Render(specs,rawValues,true); UI.Replace(note,Data.Text(d,"note","")); RenderArticle(d);
                string nextEntry=Data.Text(d,"entry_id","");
                if(nextEntry!=entry) { positions.Remove("result"); positions.Remove("edit"); entry=nextEntry; }
                if(Data.Flag(d,"focus_result")) { SetMode("result"); scroll.ScrollToTop(); Dispatcher.BeginInvoke(new Action(delegate { if(primary.IsVisible) primary.Focus(); else back.Focus(); })); }
                else if((Data.Flag(d,"focus_listing") || Data.Flag(d,"focus_suggestions")) && mode=="search" && resultButtons.Count>0) { if(Data.Flag(d,"focus_listing")) scroll.ScrollToTop(); resultButtons[0].Focus(); }
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
            var follow=UI.Name(new CheckBox { Content="跟随游戏窗口" },"跟随游戏窗口"); values["enabled"]=follow; body.Children.Add(follow); follow.Checked+=delegate { Edited(); }; follow.Unchecked+=delegate { Edited(); };
            var shortcuts=new StackPanel(); shortcuts.Children.Add(UI.Text("可以修改或清空禁用；快捷键需含 Ctrl 或 Alt。",11,UI.Muted)); foreach(string[] pair in new[]{new[]{"capture","立即备份已保存进度"},new[]{"show","显示随行助手"},new[]{"library","图鉴"},new[]{"backups","存档历史"},new[]{"play_toggle","开关游戏跟随"},new[]{"quick","收起或展开随行助手"}}) { var edit=UI.Edit(pair[1]+"快捷键",80); bindings[pair[0]]=edit; edit.TextChanged+=delegate { Edited(); }; shortcuts.Children.Add(UI.Field(pair[1],edit)); } body.Children.Add(UI.Section("全局快捷键",shortcuts,false)); body.Children.Add(UI.Section("快捷键注册状态",status,false));
            persistence=UI.Buttons(UI.Button("保存跟随与快捷键",delegate { FlushEdit(); Host.Send("settings_save","surface","settings"); },true),UI.Button("更多",delegate { var button=(Button)persistence.Children[1]; UI.Menu(button,UI.Item("重新读取跟随与快捷键",delegate { FlushEdit(); Host.Send("settings_reload","surface","settings"); }),UI.Item("完整设置面板",delegate { Host.Send("panel","page","play-settings"); })); })); persistence.Margin=new Thickness(0,10,0,0); var bottom=UI.Stack(feedback,persistence); Grid.SetRow(bottom,1); Children.Add(bottom);
        }
        void Edited() { if(rendering || !initialized || Host.Frozen) return; ++draftRevision; changed=Dirty=true; feedback.Text="已修改，尚未保存"; FlushEdit(); }
        public Dictionary<string,object> Raw() { var v=new Dictionary<string,object>(); var b=new Dictionary<string,object>(); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; v[pair.Key]=check!=null ? (object)(check.IsChecked==true) : combo!=null ? Convert.ToString(combo.SelectedItem) : text.Text; } foreach(var pair in bindings) b[pair.Key]=pair.Value.Text; return Data.Map("values",v,"bindings",b,"draft_revision",draftRevision); }
        public void FlushEdit() { if(!initialized || !changed) return; changed=false; var raw=Raw(); Host.Send("settings_edit","surface","settings","values",raw["values"],"bindings",raw["bindings"],"draft_revision",draftRevision); }
        public void Render(Dictionary<string,object> d) { persistence.IsEnabled=!Data.Flag(d,"io_busy"); if(Data.Number(d,"draft_revision")<draftRevision) return; rendering=true; try { draftRevision=Data.Number(d,"draft_revision"); var v=Data.Object(d,"values"); var b=Data.Object(d,"bindings"); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; if(check!=null) check.IsChecked=Data.Flag(v,pair.Key); else if(combo!=null) { string value=Data.Text(v,pair.Key,""); if(!combo.Items.Contains(value)) combo.Items.Add(value); combo.SelectedItem=value; } else UI.Replace(text,Data.Text(v,pair.Key,"")); } foreach(var pair in bindings) UI.Replace(pair.Value,Data.Text(b,pair.Key,"")); feedback.Text=Data.Text(d,"status",""); status.Text=Data.Text(d,"registration",""); Dirty=Data.Flag(d,"dirty"); initialized=true; } finally { rendering=false; } }
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
