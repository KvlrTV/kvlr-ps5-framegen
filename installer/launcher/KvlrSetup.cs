// KVLR edition: a one-wizard install, so a friend never has to fetch anything by hand.
// - Visual C++ runtime: the Microsoft redistributable ships inside the setup (app\redist\vc_redist.x64.exe, staged by
//   kvlr/build_kvlr.py). The PC check shows it as "Comes with SmoovPlay" instead of a fix to press first, and the
//   install step runs it when it's missing or too old (Windows asks for permission once). Its signature is checked
//   (Microsoft's, valid) before it runs; with no bundled copy it's downloaded from Microsoft as before.
// - NVIDIA VFG: an optional tick box on the folder page (RTX 40 and 50 cards only). It's NVIDIA's software under
//   NVIDIA's licence, so it's never bundled and is off until the player ticks it, which accepts that licence (with a
//   link to read it). The install then downloads it from NVIDIA (framegen.vfg_setup, as the Settings page does) before
//   the graphics-card step, so Auto-detect sees it. If that download fails, setup carries on without it: VFG can be
//   set up later on the Settings page.
// Hooks (marked KVLR): Core.cs Installer (partial) Run; Ui.cs RunChecks, CheckNext and StartInstall.

using System;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;

namespace SmoovPlay
{
    partial class Installer
    {
        public bool KvlrVfg;  // the player ticked NVIDIA VFG (and so accepted NVIDIA's licence) in setup

        static bool VcMissing()
        {
            var c = new Check("vc", "", "");
            SystemCheck.Run(c, Path.GetTempPath(), true);
            return c.Level != Level.Ok;
        }

        /// <summary>Before Python: install the Visual C++ runtime if this PC lacks it (PyTorch won't load without it).</summary>
        void KvlrVcRuntime(double at)
        {
            if (!VcMissing()) { Log("Visual C++ runtime already installed"); return; }
            Step("Installing the Microsoft Visual C++ runtime");
            string bundled = Path.Combine(p.App, "redist", "vc_redist.x64.exe");
            string err;
            if (File.Exists(bundled))
            {
                Progress(at, "Installing the Microsoft Visual C++ runtime (Windows asks for permission)");
                err = SystemCheck.SignedByMicrosoft(bundled) ? RunVcRedist(bundled) : "the bundled installer isn't signed by Microsoft";
            }
            else err = SystemCheck.InstallVcRuntime(s => Progress(at, "Visual C++ runtime: " + s));
            if (err == null && !VcMissing()) { Log("Visual C++ runtime installed"); return; }
            throw new Exception("The Microsoft Visual C++ runtime didn't install (" + (err ?? "it still isn't there") + "). "
                                + "Press Retry and allow it at the Windows prompt.");
        }

        static string RunVcRedist(string exe)
        {
            try
            {
                var psi = new ProcessStartInfo(exe, "/install /passive /norestart") { UseShellExecute = true, Verb = "runas" };
                using (var pr = Process.Start(psi))
                {
                    pr.WaitForExit();
                    // 3010: installed, restart later; 1638: a newer version is already installed
                    return pr.ExitCode == 0 || pr.ExitCode == 3010 || pr.ExitCode == 1638 ? null : "it stopped with code " + pr.ExitCode;
                }
            }
            catch (System.ComponentModel.Win32Exception e) when (e.NativeErrorCode == 1223) { return "cancelled at the Windows permission prompt"; }
            catch (Exception e) { return e.Message; }
        }

        /// <summary>After the packages, before the graphics-card step: NVIDIA VFG, if ticked. Never fails the install.</summary>
        void KvlrVfgInstall(double at, double w)
        {
            if (!KvlrVfg) return;
            Step("Downloading NVIDIA VFG from NVIDIA (the player accepted NVIDIA's licence in setup)");
            Progress(at, "Downloading NVIDIA VFG from NVIDIA");
            var progress = new Regex(@"^Progress (\d+) of (\d+)");
            string tmp = Path.Combine(p.Runtime, "tmp-vfx");
            int rc;
            try
            {
                Directory.CreateDirectory(tmp);
                string args = "-m framegen.vfg_setup --install --accept-nvidia-licence --target \"" + p.Vfx + "\"" + ProxyArg;
                rc = RunPython(args, p.App, line =>
                {
                    var m = progress.Match(line);
                    if (m.Success)
                    {
                        double c = double.Parse(m.Groups[1].Value), t = double.Parse(m.Groups[2].Value);
                        Progress(at + w * Math.Min(1, c / Math.Max(1, t)), $"Downloading NVIDIA VFG  ({c / 1e6:0} of {t / 1e6:0} MB)");
                        return;
                    }
                    Log(line);
                });
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception e) { Log("NVIDIA VFG: " + e.Message); rc = -1; }
            finally { TryDelete(tmp); }
            ThrowIfCancelled();
            Log(rc == 0 ? "NVIDIA VFG set up" : "NVIDIA VFG didn't set up (exit code " + rc + "); carrying on without it. It can be set up later on the Settings page.");
            Progress(at + w, rc == 0 ? "NVIDIA VFG ready" : "NVIDIA VFG skipped (set it up later in Settings)");
        }
    }

    partial class Ui
    {
        CheckBox kvlrVfgBox;

        /// <summary>RunChecks, setup only: the Visual C++ runtime comes with SmoovPlay, so it isn't a thing to fix first.</summary>
        static void KvlrSetupCheck(Check c, bool fresh)
        {
            if (!fresh || c.Id != "vc" || c.Level != Level.Fail) return;
            c.FixLabel = c.FixId = null;
            c.Set(Level.Info, "Comes with SmoovPlay", "Setup installs it for you. Windows asks for permission once.");
        }

        /// <summary>RTX 40 and 50 series (and newer workstation Ada/Blackwell cards): what NVIDIA VFG supports.</summary>
        static bool KvlrVfgCard()
        {
            string g = SystemCheck.GpuName ?? "";
            return Regex.IsMatch(g, @"RTX\s*[4-9]0\d0") || Regex.IsMatch(g, @"RTX.*\b(Ada|Blackwell)\b") || Regex.IsMatch(g, @"RTX PRO \d{4}");
        }

        /// <summary>CheckNext, setup only: the NVIDIA VFG tick box under "Add a desktop shortcut".</summary>
        void KvlrSetupVfgOption()
        {
            if (!setupMode || updateMode) return;
            if (kvlrVfgBox == null)
            {
                var desktop = E<CheckBox>("ToggleDesktop");
                var host = desktop.Parent as Panel;
                if (host == null) return;
                kvlrVfgBox = new CheckBox { Style = desktop.Style, IsChecked = false, Margin = new Thickness(0, 14, 0, 0) };
                var label = new TextBlock { TextWrapping = TextWrapping.Wrap, MaxWidth = 460 };
                label.Inlines.Add(new Run("Also set up NVIDIA VFG") { FontWeight = FontWeights.SemiBold });
                label.Inlines.Add(new Run(" (optional): NVIDIA's own AI frame generation for RTX 40 and 50 cards, downloaded from NVIDIA "
                                          + "(about 540 MB). Ticking this means you accept NVIDIA's licence. ") { Foreground = R("Text2") });
                var link = new Hyperlink(new Run("Read the licence")) { Foreground = R("Accent") };
                link.Click += (s, e) =>
                {
                    Proc.Open("https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/");
                    Proc.Open("https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/");
                    Proc.Open("https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/");
                };
                label.Inlines.Add(link);
                kvlrVfgBox.Content = label;
                System.Windows.Automation.AutomationProperties.SetAutomationId(kvlrVfgBox, "ToggleKvlrVfg");
                System.Windows.Automation.AutomationProperties.SetName(kvlrVfgBox, "Also set up NVIDIA VFG (accepts NVIDIA's licence)");
                host.Children.Insert(host.Children.IndexOf(desktop) + 1, kvlrVfgBox);
            }
            Show(kvlrVfgBox, KvlrVfgCard());
        }

        bool KvlrVfgPicked { get { return kvlrVfgBox != null && kvlrVfgBox.Visibility == Visibility.Visible && kvlrVfgBox.IsChecked == true; } }
    }
}
