// KVLR: automatic updates. When the launcher opens (and every 3 hours while it stays open and nobody is playing),
// it asks GitHub for the newest release. A newer one gets a prompt that installs it by itself after a short
// countdown, unless the player picks "Not now". The version list, and older setups to roll back to, are on
// gta.kvlrtv.com (KvlrSite). A copy that was rolled back isn't pushed back up to the version it left: it is only
// prompted again for a release newer than the newest one it has run. Upstream's update link in the rail stays.
using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace SmoovPlay
{
    partial class Ui
    {
        public const string KvlrSite = "https://gta.kvlrtv.com/";
        const int KvlrCountdown = 15;  // seconds before the prompt installs the update by itself
        static readonly TimeSpan KvlrRecheck = TimeSpan.FromHours(3);

        string kvlrPromptedTag;     // a release already prompted for in this run ("Not now" lasts until the next launch)
        DispatcherTimer kvlrRecheckTimer, kvlrCountTimer;

        static string KvlrHighestFile { get { return Path.Combine(Paths.SettingsDir, "kvlr-highest-version.txt"); } }

        /// <summary>The newest version this PC has run. Remembers this one when it's newer.</summary>
        static string KvlrHighest()
        {
            string stored = null;
            try { if (File.Exists(KvlrHighestFile)) stored = File.ReadAllText(KvlrHighestFile).Trim(); } catch (Exception) { }
            if (UpdateCheck.Parse(stored) == null || UpdateCheck.Compare(BuildInfo.Version, stored) > 0)
            {
                stored = BuildInfo.Version;
                try { Directory.CreateDirectory(Paths.SettingsDir); File.WriteAllText(KvlrHighestFile, stored); } catch (Exception) { }
            }
            return stored;
        }

        /// <summary>Replaces upstream's UpdateCheck.Start in StartLauncher: same rail link, plus the prompt.</summary>
        void KvlrUpdateStart()
        {
            KvlrHelpVersionsLink();
            KvlrHighest();  // remembered now, so a later rollback is recognised
            if (Environment.GetEnvironmentVariable("SMOOVPLAY_UPDATE_CHECK") == "0" || GitHub.Repo == null) return;
            KvlrCheck();
            kvlrRecheckTimer = new DispatcherTimer { Interval = KvlrRecheck };
            kvlrRecheckTimer.Tick += (s, e) => KvlrCheck();
            kvlrRecheckTimer.Start();
        }

        void KvlrCheck()
        {
            string repo = GitHub.Repo;
            Task.Run(() =>
            {
                Release rel;
                try { rel = GitHub.Newest(repo); }
                catch (Exception) { return; }  // offline or rate-limited: say nothing, try again later
                if (rel == null || UpdateCheck.Compare(rel.Tag, BuildInfo.Version) <= 0) return;
                OnUi(() =>
                {
                    ShowUpdate(rel.Tag, KvlrSite);
                    KvlrPrompt(rel);
                });
            });
        }

        /// <summary>"Update to vX?" with a countdown that installs it. Never while playing, saving a clip, or over
        /// another open dialog; never for a copy that can't update itself (it keeps the rail link).</summary>
        void KvlrPrompt(Release rel)
        {
            if (updating || rel.Tag == kvlrPromptedTag || !rel.CanInstall) return;
            if (Updater.Unavailable(paths) != null) return;
            if (session != null && session.Running) return;
            if (E("Dialog").Visibility == Visibility.Visible) return;
            string highest = KvlrHighest();
            if (UpdateCheck.Compare(rel.Tag, highest) <= 0) return;  // rolled back on purpose: stay, keep the rail link
            kvlrPromptedTag = rel.Tag;
            bool chiaki = Updater.ChiakiInInstall(paths).Length > 0;
            string mb = rel.SetupSize > 0 ? $"about {Math.Max(1, rel.SetupSize / 1048576)} MB" : "the new setup";
            string body = $"SmoovPlay downloads it ({mb}), closes, updates in a minute or two and opens again. " +
                          "Your settings, looks and clips stay." + (chiaki ? " chiaki-ng closes too, since it's updated with it." : "") +
                          " Older versions are on gta.kvlrtv.com if you ever want to go back.";
            int left = KvlrCountdown;
            Func<string> text = () => body + $"\n\nUpdating by itself in {left} s.";
            Ask("", "Accent", "Update to " + V(rel.Tag) + "?", text(), "Update now", "Not now", "All versions", r =>
            {
                KvlrStopCountdown();
                if (r == 1) UnlessSaving("Updating", RunUpdate);
                else if (r == 3) Proc.Open(KvlrSite);
            });
            kvlrCountTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            kvlrCountTimer.Tick += (s, e) =>
            {
                if (session != null && session.Running) { KvlrStopCountdown(); CloseDialog(2); return; }  // started playing
                left--;
                if (left <= 0) { KvlrStopCountdown(); CloseDialog(1); return; }
                T("DialogText").Text = text();
            };
            kvlrCountTimer.Start();
        }

        void KvlrStopCountdown()
        {
            if (kvlrCountTimer != null) kvlrCountTimer.Stop();
            kvlrCountTimer = null;
        }

        /// <summary>"All versions" next to Send feedback on the Help page: the version list and rollback setups.</summary>
        void KvlrHelpVersionsLink()
        {
            var feedback = B("HelpFeedback");
            var row = feedback != null ? feedback.Parent as StackPanel : null;
            if (row == null || row.FindName("HelpKvlrVersions") != null) return;
            var link = new Button
            {
                Name = "HelpKvlrVersions",
                Content = "All versions",
                Style = feedback.Style,
                ToolTip = "Opens gta.kvlrtv.com: every version, with what changed, and older setups to go back to.",
            };
            System.Windows.Automation.AutomationProperties.SetAutomationId(link, "HelpKvlrVersions");
            link.Click += (s, e) => Proc.Open(KvlrSite + "#versions");
            row.Children.Insert(0, link);
        }
    }
}
