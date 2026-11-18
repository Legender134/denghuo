using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace Denghuo.Native {
    // An explicit, reversible windowed display mode. Never fights a fullscreen
    // game's Z-order, changes monitor ownership, or captures/hides the cursor.
    sealed class GameDisplay {
        const long Frame = 0x00C40000, Popup = 0x80000000;
        const uint FrameChanged = 0x20, NoActivate = 0x10, NoOwnerOrder = 0x200;
        [StructLayout(LayoutKind.Sequential)] struct Point { public int X,Y; }
        [StructLayout(LayoutKind.Sequential)] struct Rect {
            public int Left,Top,Right,Bottom;
            public bool Same(Rect b) { return Left==b.Left && Top==b.Top && Right==b.Right && Bottom==b.Bottom; }
        }
        [StructLayout(LayoutKind.Sequential)] struct Placement {
            public int Length,Flags,Show; public Point Minimum,Maximum; public Rect Normal;
        }
        [StructLayout(LayoutKind.Sequential)] struct Monitor { public int Size; public Rect Bounds,Work; public uint Flags; }
        delegate bool EnumWindow(IntPtr hwnd,IntPtr data);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindow callback,IntPtr data);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd,StringBuilder text,int size);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd,StringBuilder text,int size);
        [DllImport("user32.dll",SetLastError=true)] static extern bool GetWindowRect(IntPtr hwnd,out Rect rect);
        [DllImport("user32.dll",SetLastError=true)] static extern bool GetWindowPlacement(IntPtr hwnd,ref Placement placement);
        [DllImport("user32.dll",SetLastError=true)] static extern bool SetWindowPlacement(IntPtr hwnd,ref Placement placement);
        [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr hwnd,uint flags);
        [DllImport("user32.dll",SetLastError=true)] static extern bool GetMonitorInfo(IntPtr monitor,ref Monitor info);
        [DllImport("user32.dll",EntryPoint="GetWindowLongPtrW",SetLastError=true)] static extern IntPtr GetLong64(IntPtr hwnd,int index);
        [DllImport("user32.dll",EntryPoint="GetWindowLongW",SetLastError=true)] static extern int GetLong32(IntPtr hwnd,int index);
        [DllImport("user32.dll",EntryPoint="SetWindowLongPtrW",SetLastError=true)] static extern IntPtr SetLong64(IntPtr hwnd,int index,IntPtr value);
        [DllImport("user32.dll",EntryPoint="SetWindowLongW",SetLastError=true)] static extern int SetLong32(IntPtr hwnd,int index,int value);
        [DllImport("kernel32.dll")] static extern void SetLastError(uint error);
        [DllImport("user32.dll",SetLastError=true)] static extern bool SetWindowPos(IntPtr hwnd,IntPtr after,int x,int y,int width,int height,uint flags);

        IntPtr remembered,active;
        uint rememberedPid,activePid;
        long originalStyle;
        Placement originalPlacement,appliedPlacement;
        Rect originalBounds,appliedBounds;
        public bool Active { get {
            if(active!=IntPtr.Zero && (!Valid(active,activePid) || (Long(active,-16)&Popup)!=0)) active=IntPtr.Zero;
            return active!=IntPtr.Zero;
        } }
        public Dictionary<string,object> Game { get { return new Dictionary<string,object> {{"hwnd",remembered.ToInt64()},{"pid",rememberedPid}}; } }
        public bool CanReturnFocus { get { return Valid(remembered,rememberedPid) && !IsIconic(remembered); } }
        static long Long(IntPtr hwnd,int index) { return IntPtr.Size==8 ? GetLong64(hwnd,index).ToInt64() : (long)(uint)GetLong32(hwnd,index); }
        static void Style(IntPtr hwnd,long value) {
            SetLastError(0);
            long before=IntPtr.Size==8 ? SetLong64(hwnd,-16,new IntPtr(value)).ToInt64() : SetLong32(hwnd,-16,unchecked((int)value));
            if(before==0 && Marshal.GetLastWin32Error()!=0) throw new Win32Exception();
        }
        static bool IsGame(IntPtr hwnd,out uint pid) {
            pid=0;
            if(hwnd==IntPtr.Zero || !IsWindow(hwnd)) return false;
            GetWindowThreadProcessId(hwnd,out pid);
            if(pid==0 || pid==(uint)System.Diagnostics.Process.GetCurrentProcess().Id) return false;
            var title=new StringBuilder(512); var kind=new StringBuilder(128);
            GetWindowText(hwnd,title,title.Capacity); GetClassName(hwnd,kind,kind.Capacity);
            return title.ToString().StartsWith("Shattered Pixel Dungeon",StringComparison.Ordinal) &&
                (kind.ToString()=="GLFW30" || kind.ToString()=="LWJGL");
        }
        static bool Valid(IntPtr hwnd,uint expected) { uint actual; return IsGame(hwnd,out actual) && actual==expected; }
        IntPtr Target() {
            IntPtr found=IntPtr.Zero; uint foundPid=0; int count=0;
            EnumWindows(delegate(IntPtr hwnd,IntPtr data) { uint pid;
                if(IsWindowVisible(hwnd) && IsGame(hwnd,out pid)) { found=hwnd; foundPid=pid; count++; }
                return true;
            },IntPtr.Zero);
            if(count!=1) throw new InvalidOperationException(count==0 ? "请先打开游戏。" : "当前有多个游戏窗口，请保留一个后再开启兼容全屏。");
            remembered=found; rememberedPid=foundPid; return found;
        }
        public void Enable() {
            if(Active) return;
            IntPtr hwnd=Target();
            long style=Long(hwnd,-16);
            if((style & 0x00C00000)!=0x00C00000 || (style & Popup)!=0)
                throw new InvalidOperationException("请先在游戏设置中关闭“全屏模式”，再开启兼容全屏。");
            if(IsIconic(hwnd)) throw new InvalidOperationException("请先返回游戏，再开启兼容全屏。");
            var placement=new Placement { Length=Marshal.SizeOf(typeof(Placement)) };
            var monitor=new Monitor { Size=Marshal.SizeOf(typeof(Monitor)) };
            Rect bounds;
            if(!GetWindowPlacement(hwnd,ref placement) || !GetWindowRect(hwnd,out bounds) ||
                !GetMonitorInfo(MonitorFromWindow(hwnd,2),ref monitor)) throw new Win32Exception();
            active=hwnd; activePid=rememberedPid; originalStyle=style;
            originalPlacement=placement; originalBounds=bounds; appliedBounds=monitor.Bounds;
            try {
                if(!Valid(hwnd,activePid)) throw new InvalidOperationException("游戏窗口已改变，请重试。");
                // Keep the existing maximized/show state; never activate or
                // unmaximize the game as a side effect of entering this mode.
                Style(hwnd,Long(hwnd,-16)&~Frame);
                if(!SetWindowPos(hwnd,IntPtr.Zero,appliedBounds.Left,appliedBounds.Top,
                    appliedBounds.Right-appliedBounds.Left,appliedBounds.Bottom-appliedBounds.Top,FrameChanged|NoActivate|NoOwnerOrder|4)) throw new Win32Exception();
                appliedPlacement=new Placement { Length=Marshal.SizeOf(typeof(Placement)) };
                if(!GetWindowPlacement(hwnd,ref appliedPlacement)) throw new Win32Exception();
            } catch(Exception error) {
                try { Restore(true); }
                catch(Win32Exception recovery) {
                    throw new InvalidOperationException("切换未完成："+error.Message+"；恢复窗口失败，请再次点击兼容全屏重试："+recovery.Message,error);
                }
                throw;
            }
        }
        public void Restore() { Restore(false); }
        void Restore(bool rollback) {
            if(active==IntPtr.Zero) return;
            if(!Valid(active,activePid)) { active=IntPtr.Zero; return; }
            long style=Long(active,-16);
            // The player may have enabled the game's own fullscreen since then.
            // Do not overwrite that newer mode or a recycled HWND.
            if((style&Popup)!=0) { active=IntPtr.Zero; return; }
            Rect current;
            var currentPlacement=new Placement { Length=Marshal.SizeOf(typeof(Placement)) };
            if(!GetWindowRect(active,out current) || !GetWindowPlacement(active,ref currentPlacement)) throw new Win32Exception();
            bool minimized=IsIconic(active);
            // Both normal rectangles are WINDOWPLACEMENT workspace coordinates.
            // A minimized icon's screen rectangle is not its restored geometry.
            bool unchanged=rollback || (minimized ? currentPlacement.Normal.Same(appliedPlacement.Normal) : current.Same(appliedBounds));
            Style(active,(style&~Frame)|(originalStyle&Frame));
            if(unchanged) {
                var restore=originalPlacement;
                // SW_SHOWNA preserves the current normal/maximized state without
                // activation. SW_SHOWMINNOACTIVE keeps a minimized game minimized.
                restore.Show=minimized ? 7 : 8;
                // WPF_RESTORETOMAXIMIZED is valid only with SW_SHOWMINIMIZED.
                // Never combine it with the non-activating show commands here.
                restore.Flags=0;
                if(!SetWindowPlacement(active,ref restore)) throw new Win32Exception();
            }
            // If the player moved/resized it, preserve their newer geometry.
            uint flags=FrameChanged|NoActivate|NoOwnerOrder|4; // NOZORDER: never demote owned tool windows.
            if(!unchanged || minimized) flags|=3;
            if(!SetWindowPos(active,IntPtr.Zero,originalBounds.Left,originalBounds.Top,
                originalBounds.Right-originalBounds.Left,originalBounds.Bottom-originalBounds.Top,flags)) throw new Win32Exception();
            active=IntPtr.Zero;
        }
    }
}
