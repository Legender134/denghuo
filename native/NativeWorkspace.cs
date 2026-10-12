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
                    else { var text=UI.Edit(label,numeric ? 80 : 1200); text.TextChanged+=delegate { Edited(key,false); }; control=text; }
                    controls[key]=control; var title=UI.Text(label,12,UI.Muted); title.Margin=new Thickness(0,0,0,6); var hint=UI.Text("",11,UI.Muted); hint.Margin=new Thickness(0,4,0,0); hints[key]=hint; var field=UI.Stack(title,control,hint); field.Margin=new Thickness(0,0,0,14); group.Children.Add(field);
                } signature=next; }
                foreach(object item in fields) { var spec=(Dictionary<string,object>)item; string key=Data.Text(spec,"key",""), value=Data.Text(values,key,""); var control=controls[key]; var text=control as TextBox; var combo=control as ComboBox; var multi=control as StackPanel;
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
        public SavedMap() { Height=230; Margin=new Thickness(0,12,0,16); UI.Name(this,"保存地图 · 未知区域保持遮住，金色为角色，绿色为楼梯"); }
        public void Render(Dictionary<string,object> value) { data=value; Visibility=Data.Array(value,"tiles").Length>0 ? Visibility.Visible : Visibility.Collapsed; InvalidateVisual(); }
        protected override void OnRender(DrawingContext context) { int width=(int)Data.Number(data,"width"), height=(int)Data.Number(data,"height"); var tiles=Data.Array(data,"tiles"); if(width<1 || height<1 || tiles.Length!=width*height) return; double size=Math.Min(ActualWidth/width,ActualHeight/height), left=(ActualWidth-width*size)/2, top=(ActualHeight-height*size)/2; for(int i=0;i<tiles.Length;i++) { int tile=Convert.ToInt32(tiles[i]); Brush brush=tile<0 ? UI.Background : tile==4 || tile==0 || tile==23 ? UI.Line : tile==7 || tile==8 ? UI.Brush("#74998A") : tile==16 || tile==17 ? UI.Gold : UI.Brush("#929AA8"); if(data.ContainsKey("hero") && data["hero"]!=null && Convert.ToInt32(data["hero"])==i) brush=UI.Gold; context.DrawRectangle(brush,null,new Rect(left+(i%width)*size,top+(i/width)*size,Math.Max(1,size-.65),Math.Max(1,size-.65))); } }
    }

    sealed class TaskPane : Grid {
        readonly Helper host; readonly string page;
        readonly FieldEditor fields=new FieldEditor();
        readonly StackPanel output=new StackPanel(), article=new StackPanel(), selector=new StackPanel();
        readonly StackPanel comparison=new StackPanel();
        readonly SavedMap map=new SavedMap();
        readonly ScrollViewer scroll;
        readonly WrapPanel actions=new WrapPanel();
        readonly Button mode;
        readonly Expander selection;
        readonly Expander details;
        readonly Dictionary<string,double> positions=new Dictionary<string,double>();
        bool rendering,editing;
        long revision;
        string articleText="", rowSignature="";
        Dictionary<string,object> values=new Dictionary<string,object>();
        public bool Dirty;
        public TaskPane(Helper owner,string name) {
            host=owner; page=name; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            mode=UI.Button("编辑条件",delegate { SetEditing(!editing); }); mode.HorizontalAlignment=HorizontalAlignment.Left; mode.Background=Brushes.Transparent; Children.Add(mode);
            selection=UI.Section(page=="inventory" ? "选择背包物品" : page=="map" ? "选择保存楼层" : "选择存档记录",selector,true); output.Children.Add(selection); output.Children.Add(map); if(page=="equipment") { output.Children.Add(comparison); details=UI.Section("完整数值与条件",article,true); output.Children.Add(details); } else output.Children.Add(article); scroll=UI.Scroll(output); Grid.SetRow(scroll,1); Children.Add(scroll); actions.Margin=new Thickness(0,10,0,0); Grid.SetRow(actions,2); Children.Add(actions);
            fields.Changed=delegate(string key,bool structural) { if(rendering || host.Frozen) return; ++revision; Dirty=true; values=fields.Raw(); host.Send("game_edit","page",page,"values",values,"draft_revision",revision,"structure",structural); if(key!="name" && key!="note") { articleText="条件已修改，请重新计算。原始输入已保留。"; UI.Article(article,articleText); comparison.Children.Clear(); if(details!=null) details.IsExpanded=true; } };
        }
        public Dictionary<string,object> Raw() { return fields.Raw(); }
        public void Flush() { host.Send("game_edit","page",page,"values",Raw(),"draft_revision",revision); }
        void SetEditing(bool value) { positions[editing ? "edit" : "result"]=scroll.VerticalOffset; editing=value; mode.Content=editing ? "查看结果" : "编辑条件"; UI.Name(mode,editing ? "查看结果" : "编辑条件"); scroll.Content=editing ? (object)fields : output; double position; scroll.ScrollToVerticalOffset(positions.TryGetValue(editing ? "edit" : "result",out position) ? position : 0); UI.Fade(scroll); }
        void RenderComparison(Dictionary<string,object> data) {
            comparison.Children.Clear(); var choices=Data.Array(data,"choices"); details.IsExpanded=choices.Length!=2; if(choices.Length!=2) return;
            comparison.Children.Add(UI.Text("A · "+Data.Text((Dictionary<string,object>)choices[0],"name","")+"\nB · "+Data.Text((Dictionary<string,object>)choices[1],"name",""),15));
            var planning=Data.Object(data,"planning"); if(planning.Count>0) { var pending=new List<string>(); int n=0; foreach(object item in Data.Array(planning,"choices")) { var side=(Dictionary<string,object>)item; string label=n++==0 ? "A" : "B"; if(Data.Flag(side,"upgrade_pending")) pending.Add(label); } if(pending.Count>0) { var notice=UI.Text("预算待确认 · "+String.Join("、",pending.ToArray())+" 注魔假设未确认",13,UI.Gold); notice.Margin=new Thickness(0,12,0,8); comparison.Children.Add(notice); } comparison.Children.Add(UI.Text("预算 "+Data.Text(planning,"upgrade_budget","0")+" 卷 / "+Data.Text(planning,"strength_budget","0")+" 瓶力量药剂；A、B分别使用同一预算，不能同时花费。",12,UI.Muted)); n=0; foreach(object item in Data.Array(planning,"choices")) { var side=(Dictionary<string,object>)item; comparison.Children.Add(UI.Text((n++==0 ? "A" : "B")+" · 投入 "+Data.Text(side,"spent_upgrades","?")+" 卷，余 "+Data.Text(side,"remaining_upgrades","?")+" 卷",12)); } }
            comparison.Children.Add(UI.Text("当前 → 升级一次",11,UI.Muted)); var grid=new Grid { Margin=new Thickness(0,12,0,14) }; grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1.2,GridUnitType.Star) }); grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition()); int row=0; foreach(object item in Data.Array(data,"rows")) { var metric=(Dictionary<string,object>)item; var cells=Data.Array(metric,"values"); if(cells.Length!=4) continue; grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); var label=UI.Text(Data.Text(metric,"label",""),12,UI.Muted); label.Margin=new Thickness(0,7,6,7); Grid.SetRow(label,row); grid.Children.Add(label); for(int i=0;i<2;i++) { var value=UI.Text((i==0 ? "A " : "B ")+Convert.ToString(cells[i*2])+" → "+Convert.ToString(cells[i*2+1]),12); value.Margin=new Thickness(0,7,5,7); Grid.SetRow(value,row); Grid.SetColumn(value,i+1); value.ToolTip=Data.Text(metric,"condition",""); grid.Children.Add(value); } row++; } comparison.Children.Add(grid); comparison.Children.Add(UI.Text(Data.Text(data,"notice",""),11,UI.Muted));
        }
        public void Render(Dictionary<string,object> d) {
            if(Data.Number(d,"draft_revision")<revision) return; rendering=true; try { revision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty"); values=new Dictionary<string,object>(Data.Object(d,"raw")); object[] specs=Data.Array(d,"fields"); bool first=fields.Children.Count==0; fields.Render(specs,values); mode.Visibility=specs.Length>0 ? Visibility.Visible : Visibility.Collapsed; if(first && specs.Length>0) SetEditing(true);
                string text=Data.Text(d,"text",""); if(text!=articleText) { articleText=text; UI.Article(article,text); if(page=="equipment") RenderComparison(Data.Object(d,"comparison")); }
                map.Render(Data.Object(d,"map")); var rows=Data.Array(d,"rows"); string next=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(rows)+Data.Text(d,"selected",""); if(next!=rowSignature) { selector.Children.Clear(); foreach(object item in rows) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""), token=Data.Text(row,"token",""); var button=UI.Button("",delegate { if(!host.Frozen) { host.Send("game_select","page",page,"id",id,"token",token); selection.IsExpanded=false; } }); string caption=Data.Text(row,"text",""); button.Content=UI.Text(caption); UI.Name(button,caption); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; button.Margin=new Thickness(0,0,0,5); if(id==Data.Text(d,"selected","")) button.BorderThickness=new Thickness(1); selector.Children.Add(button); } rowSignature=next; } selection.Visibility=rows.Length>0 ? Visibility.Visible : Visibility.Collapsed;
                actions.Children.Clear(); var extras=new List<MenuItem>(); Button more=null; foreach(object item in Data.Array(d,"actions")) { var action=(Dictionary<string,object>)item; string command=Data.Text(action,"id",""); Action clicked=delegate { if(host.Frozen) return; Flush(); host.Send("game_action","page",page,"command",command,"values",Raw(),"draft_revision",revision); }; string label=Data.Text(action,"text",""); bool disabled=Data.Flag(action,"disabled"); if(command=="calculate" || command=="save" || command=="inventory_reveal" || command=="map_reveal" || command=="backup_preview" || actions.Children.Count<2 && command!="update") { var button=UI.Button(label,clicked,command=="calculate"); button.IsEnabled=!disabled; actions.Children.Add(button); } else extras.Add(UI.Item(label,clicked,!disabled)); }
                if(extras.Count>0) { more=UI.Button("更多操作",delegate { UI.Menu(more,extras.ToArray()); }); actions.Children.Add(more); }
                if(Data.Flag(d,"focus_result")) { SetEditing(false); scroll.ScrollToTop(); }
            } finally { rendering=false; }
        }
    }

    sealed class LookupForm : Grid {
        readonly Helper Host;
        readonly TextBox search=UI.Edit("搜索物品、敌人或技能",200), note=UI.Edit("用户用途或假设备注",1200);
        readonly FieldEditor fields=new FieldEditor();
        readonly StackPanel output=new StackPanel(), article=new StackPanel(), candidates=new StackPanel(), parameterBody=new StackPanel();
        readonly ScrollViewer scroll;
        readonly Expander results;
        readonly TextBlock status=UI.Text("",11,UI.Muted);
        readonly Button conditions, more;
        readonly List<Dictionary<string,object>> sources=new List<Dictionary<string,object>>();
        Dictionary<string,object> state=new Dictionary<string,object>();
        bool rendering,changed,editing;
        long draftRevision;
        string resultText="",rowsSignature="";
        Button moreResults;
        public bool Dirty;
        public UIElement Editable { get { return this; } }
        public LookupForm(Helper host) {
            Host=host; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
            search.Margin=new Thickness(0,0,0,9); search.ToolTip="搜索物品、敌人或技能 · Enter打开第一项"; var searchShell=new Grid(); searchShell.Children.Add(search); var placeholder=UI.Text("搜索物品、怪物或技能…",12,UI.Muted); placeholder.Margin=new Thickness(11,7,10,16); placeholder.IsHitTestVisible=false; searchShell.Children.Add(placeholder); search.TextChanged+=delegate { placeholder.Visibility=search.Text.Length==0 ? Visibility.Visible : Visibility.Collapsed; }; Children.Add(searchShell);
            conditions=UI.Button("编辑条件",delegate { SetEditing(!editing); }); more=UI.Button("资料操作",ShowActions); var bar=UI.Buttons(conditions,more); Grid.SetRow(bar,1); Children.Add(bar);
            moreResults=UI.Button("显示更多结果",delegate { Host.Send("more","surface","lookup"); });
            results=UI.Section("搜索结果",UI.Stack(candidates,moreResults),true); output.Children.Add(results); output.Children.Add(article); scroll=UI.Scroll(output); Grid.SetRow(scroll,2); Children.Add(scroll);
            var calculate=UI.Button("重新计算",delegate { FlushEdit(); Host.Send("calculate","surface","lookup"); SetEditing(false); },true); var bottom=UI.Stack(status,UI.Buttons(calculate,UI.Button("方案",delegate { FlushEdit(); Host.Send("save_plan","surface","lookup"); }))); bottom.Margin=new Thickness(0,8,0,0); Grid.SetRow(bottom,3); Children.Add(bottom);
            search.TextChanged+=delegate { if(!rendering && !Host.Frozen) { results.IsExpanded=true; Host.Send("query","surface","lookup","text",search.Text); } }; search.KeyDown+=delegate(object s,KeyEventArgs e) { if(e.Key==Key.Enter) { Host.Send("first","surface","lookup"); e.Handled=true; } };
            parameterBody.Children.Add(fields); parameterBody.Children.Add(UI.Field("用户用途 / 假设备注（可选，未验证）",note));
            fields.Changed=delegate { Edited(); }; note.AcceptsReturn=true; note.MinHeight=90; note.TextWrapping=TextWrapping.Wrap; note.TextChanged+=delegate { Edited(); };
        }
        void SetEditing(bool value) { editing=value; conditions.Content=value ? "查看结果" : "编辑条件"; UI.Name(conditions,Convert.ToString(conditions.Content)); scroll.Content=value ? (object)parameterBody : output; scroll.ScrollToTop(); UI.Fade(scroll); }
        void Edited() { if(rendering || Host.Frozen) return; ++draftRevision; changed=Dirty=true; resultText="参数或备注已修改，请核对并重新计算。"; UI.Article(article,resultText); status.Text="有未保存草稿"; FlushEdit(); }
        public Dictionary<string,object> Raw() { var raw=Data.Map("values",fields.Raw(),"note",UI.Note(note.Text),"draft_revision",draftRevision); Host.CaptureSaveDraft(raw); return raw; }
        public void FlushEdit() { if(!changed) return; changed=false; var raw=Raw(); Host.Send("edit","surface","lookup","values",raw["values"],"note",raw["note"],"draft_revision",draftRevision); }
        public void FocusSearch() { search.Focus(); search.SelectAll(); }
        void ShowActions() { var items=new List<MenuItem>(); foreach(string[] pair in new[]{new[]{"收藏 / 取消收藏","favorite"},new[]{"保存 / 更新 / 另存方案","save_plan"},new[]{"打开我的方案","choose_plan"},new[]{"重新读取当前方案","reload_plan"},new[]{"固定到游戏速查","pin"},new[]{"清除固定","clear_pin"},new[]{"来源与适用限制","provenance"},new[]{"撤回本次参数导入","undo_import"},new[]{"带入最新角色状态","use_latest"}}) { string action=pair[1]; bool enabled=action=="undo_import" ? Data.Flag(state,"undo") : action=="use_latest" ? Data.Flag(state,"can_latest") : true; items.Add(UI.Item(pair[0],delegate { FlushEdit(); Host.Send(action,"surface","lookup"); },enabled)); }
            int n=0; string token=Data.Text(state,"sources_token",""); foreach(var link in sources) { int index=n++; items.Add(UI.Item("官方依据 · "+Data.Text(link,"label",""),delegate { Host.Send("source_link","surface","lookup","index",index,"token",token); })); }
            items.Add(UI.Item("完整资料库",delegate { Host.Send("panel","page","workspace"); })); UI.Menu(more,items.ToArray()); }
        public void Render(Dictionary<string,object> d) { if(Data.Number(d,"draft_revision")<draftRevision) return; rendering=true; try { state=d; draftRevision=Data.Number(d,"draft_revision"); Dirty=Data.Flag(d,"dirty"); if(!search.IsKeyboardFocused) UI.Replace(search,Data.Text(d,"query","")); var rows=Data.Array(d,"rows"); string signature=new JavaScriptSerializer { MaxJsonLength=524288 }.Serialize(rows); if(signature!=rowsSignature) { candidates.Children.Clear(); int n=0; foreach(object item in rows) { var row=(Dictionary<string,object>)item; int index=n++; string token=Data.Text(row,"token",""); var button=UI.Button("",delegate { if(Host.Frozen) return; Host.Send("select","surface","lookup","index",index,"token",token); results.IsExpanded=false; SetEditing(false); }); string text=Data.Text(row,"text",""); button.Content=UI.Text(text); UI.Name(button,text); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; candidates.Children.Add(button); } rowsSignature=signature; } moreResults.Visibility=Data.Flag(d,"can_more") ? Visibility.Visible : Visibility.Collapsed; results.Visibility=rows.Length>0 ? Visibility.Visible : Visibility.Collapsed;
            object[] specs=Data.Array(d,"fields"); var rawValues=new Dictionary<string,object>(); foreach(object item in specs) { var spec=(Dictionary<string,object>)item; rawValues[Data.Text(spec,"key","")]=Data.Text(spec,"raw",""); } fields.Render(specs,rawValues,true); conditions.IsEnabled=specs.Length>0; if(specs.Length==0 && editing) SetEditing(false); UI.Replace(note,Data.Text(d,"note","")); string value=Data.Text(d,"result",""); if(value!=resultText) { resultText=value; UI.Article(article,value); } status.Text=Data.Text(d,"status",""); sources.Clear(); foreach(object item in Data.Array(d,"sources")) sources.Add((Dictionary<string,object>)item);
        } finally { rendering=false; } }
    }

    sealed class SettingsForm : Grid {
        readonly Helper Host;
        readonly StackPanel body=new StackPanel();
        readonly Dictionary<string,Control> values=new Dictionary<string,Control>();
        readonly Dictionary<string,TextBox> bindings=new Dictionary<string,TextBox>();
        readonly TextBlock status=UI.Text("",12,UI.Muted);
        readonly WrapPanel persistence;
        bool rendering,changed,initialized;
        long draftRevision;
        public bool Dirty;
        public FrameworkElement Connection;
        public UIElement Editable { get { return this; } }
        public void Prepend(FrameworkElement connection) { body.Children.Insert(0,UI.Section("连接与存档",connection,false)); }
        public SettingsForm(Helper host) {
            Host=host; RowDefinitions.Add(new RowDefinition()); RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); var scroll=UI.Scroll(body); Children.Add(scroll);
            foreach(string[] pair in new[]{new[]{"enabled","启用游玩显示"},new[]{"alerts","新存档新风险短暂提示"}}) { var check=UI.Name(new CheckBox { Content=pair[1] },pair[1]); values[pair[0]]=check; body.Children.Add(check); check.Checked+=delegate { Edited(); }; check.Unchecked+=delegate { Edited(); }; }
            body.Children.Add(UI.Text("仅跟随游戏前台，显示最近保存的参考数据。",11,UI.Muted)); var display=new StackPanel(); var anchor=UI.Combo("显示角落","左上","右上","左下","右下"); values["anchor"]=anchor; anchor.SelectionChanged+=delegate { Edited(); }; display.Children.Add(UI.Field("显示角落",anchor));
            foreach(string[] pair in new[]{new[]{"offset_x","横向边距"},new[]{"offset_y","纵向边距"},new[]{"font_scale","字号倍率（1–2）"},new[]{"opacity","背景不透明度（0.5–1）"},new[]{"notice_seconds","短提醒时长（3–30秒）"}}) { var edit=UI.Edit(pair[1],80); values[pair[0]]=edit; edit.TextChanged+=delegate { Edited(); }; display.Children.Add(UI.Field(pair[1],edit)); } body.Children.Add(UI.Section("游玩显示",display,true));
            var shortcuts=new StackPanel(); shortcuts.Children.Add(UI.Text("可以修改或清空禁用；快捷键需含 Ctrl 或 Alt。",11,UI.Muted)); foreach(string[] pair in new[]{new[]{"capture","立即备份已落盘进度"},new[]{"show","显示管理窗口"},new[]{"library","数值手册"},new[]{"backups","存档历史"},new[]{"play_toggle","开关游玩显示"},new[]{"quick","游戏内只读速查"}}) { var edit=UI.Edit(pair[1]+"快捷键",80); bindings[pair[0]]=edit; edit.TextChanged+=delegate { Edited(); }; shortcuts.Children.Add(UI.Field(pair[1],edit)); } body.Children.Add(UI.Section("全局快捷键",shortcuts,false)); body.Children.Add(UI.Section("保存与注册状态",status,true));
            persistence=UI.Buttons(UI.Button("保存设置",delegate { FlushEdit(); Host.Send("settings_save","surface","settings"); },true),UI.Button("更多",delegate { var button=(Button)persistence.Children[1]; UI.Menu(button,UI.Item("重新读取保存值",delegate { FlushEdit(); Host.Send("settings_reload","surface","settings"); }),UI.Item("拖动游玩显示位置",delegate { FlushEdit(); Host.Send("unlock","surface","settings"); }),UI.Item("完整设置面板",delegate { Host.Send("panel","page","play-settings"); })); })); persistence.Margin=new Thickness(0,10,0,0); Grid.SetRow(persistence,1); Children.Add(persistence);
        }
        void Edited() { if(rendering || !initialized || Host.Frozen) return; ++draftRevision; changed=Dirty=true; FlushEdit(); }
        public Dictionary<string,object> Raw() { var v=new Dictionary<string,object>(); var b=new Dictionary<string,object>(); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; v[pair.Key]=check!=null ? (object)(check.IsChecked==true) : combo!=null ? Convert.ToString(combo.SelectedItem) : text.Text; } foreach(var pair in bindings) b[pair.Key]=pair.Value.Text; return Data.Map("values",v,"bindings",b,"draft_revision",draftRevision); }
        public void FlushEdit() { if(!initialized || !changed) return; changed=false; var raw=Raw(); Host.Send("settings_edit","surface","settings","values",raw["values"],"bindings",raw["bindings"],"draft_revision",draftRevision); }
        public void Render(Dictionary<string,object> d) { persistence.IsEnabled=!Data.Flag(d,"io_busy"); if(Data.Number(d,"draft_revision")<draftRevision) return; rendering=true; try { draftRevision=Data.Number(d,"draft_revision"); var v=Data.Object(d,"values"); var b=Data.Object(d,"bindings"); foreach(var pair in values) { var check=pair.Value as CheckBox; var combo=pair.Value as ComboBox; var text=pair.Value as TextBox; if(check!=null) check.IsChecked=Data.Flag(v,pair.Key); else if(combo!=null) { string value=Data.Text(v,pair.Key,""); if(!combo.Items.Contains(value)) combo.Items.Add(value); combo.SelectedItem=value; } else UI.Replace(text,Data.Text(v,pair.Key,"")); } foreach(var pair in bindings) UI.Replace(pair.Value,Data.Text(b,pair.Key,"")); status.Text=Data.Text(d,"status","")+"\n\n"+Data.Text(d,"registration",""); Dirty=Data.Flag(d,"dirty"); initialized=true; } finally { rendering=false; } }
    }

    sealed class PlansForm : Grid {
        readonly Helper Host; readonly TextBox search=UI.Edit("按方案名称或备注搜索",200);
        readonly ComboBox kind=UI.Combo("方案类型","全部类型","数值方案","装备方案","炼金方案","手动草稿","角色条件"), order=UI.Combo("方案排序","最近更新","名称");
        readonly StackPanel rows=new StackPanel(); bool rendering;
        public PlansForm(Helper host) { Host=host; RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto }); RowDefinitions.Add(new RowDefinition()); var filters=UI.Stack(UI.Field("搜索方案",search),UI.Field("类型",kind),UI.Field("排序",order)); var fold=UI.Section("筛选我的方案",filters,false); Children.Add(fold); var scroll=UI.Scroll(rows); Grid.SetRow(scroll,1); Children.Add(scroll); search.TextChanged+=delegate { Filter(); }; kind.SelectionChanged+=delegate { Filter(); }; order.SelectionChanged+=delegate { Filter(); }; }
        void Filter() { if(!rendering && !Host.Frozen) Host.Send("filter_plans","surface","lookup","query",search.Text,"kind",Convert.ToString(kind.SelectedItem),"order",Convert.ToString(order.SelectedItem)); }
        public void Render(Dictionary<string,object> d) { rendering=true; try { rows.Children.Clear(); foreach(object item in Data.Array(d,"rows")) { var row=(Dictionary<string,object>)item; string id=Data.Text(row,"id",""); var button=UI.Button("",delegate { if(!Host.Frozen) Host.Send("open_plan","surface","lookup","id",id); }); string text=Data.Text(row,"text",""); button.Content=UI.Text(text); UI.Name(button,text); button.HorizontalContentAlignment=HorizontalAlignment.Stretch; rows.Children.Add(button); } if(rows.Children.Count==0) rows.Children.Add(UI.Text("没有匹配的方案。可以修改筛选，或先保存一个方案。",13,UI.Muted)); } finally { rendering=false; } }
    }
}
