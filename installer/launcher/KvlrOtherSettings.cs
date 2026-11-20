// KVLR edition: "Other settings" in each Settings card. The rows that aren't in use (a switch that's off, a choice at
// Off / 0 / None, or a setting not used with the picked source) fold away under "Other settings (N)" at the bottom of
// the card, so each card shows what is actually doing something. A setting that only matters with one of those
// (upstream's "applies") goes with it. The split is worked out when the page opens, a tab is picked or the list is
// rebuilt, not on every change, so a row doesn't jump away while you're using it. Whether a card's Other settings is
// open is remembered (launcher prefs, "set-other:<group>").
// Hooks (marked KVLR) in SettingsPage.cs: SettingRow/SettingSection fields, BuildSection, ShowSettings, BuildSettings
// and RefreshSettings; in KvlrSettingsLayout.cs the tab click.

using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;

namespace SmoovPlay
{
    partial class Ui
    {
        bool kvlrSplitDue = true;

        /// <summary>BuildSection: the card's rows panel becomes the in-use rows, with the folding Other settings under it.</summary>
        void KvlrOtherBuild(SettingSection sec, StackPanel rows, StackPanel body)
        {
            sec.KvlrMain = rows;
            sec.KvlrOther = new StackPanel();
            bool open = prefs.Contains("set-other:" + sec.Group);

            var head = new Grid();
            head.ColumnDefinitions.Add(new ColumnDefinition());
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            sec.KvlrOtherLabel = new TextBlock { FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = R("Text2"), VerticalAlignment = VerticalAlignment.Center };
            head.Children.Add(sec.KvlrOtherLabel);
            sec.KvlrOtherChevron = new RotateTransform(open ? 180 : 0);
            var chev = new TextBlock
            {
                Style = S("Icon"), Text = "", FontSize = 11, Foreground = R("Muted"), Margin = new Thickness(10, 0, 2, 0),
                RenderTransformOrigin = new Point(0.5, 0.5), RenderTransform = sec.KvlrOtherChevron, VerticalAlignment = VerticalAlignment.Center,
            };
            Grid.SetColumn(chev, 1);
            head.Children.Add(chev);
            var btn = new Button { Style = S("Fold"), Padding = new Thickness(18, 10, 18, 10), Content = head };
            AutomationProperties.SetAutomationId(btn, "SetOther_" + sec.Group.Replace(" ", ""));
            AutomationProperties.SetItemStatus(btn, open ? "open" : "closed");
            btn.Click += (s, e) =>
            {
                bool now = sec.KvlrOther.Visibility != Visibility.Visible;
                Show(sec.KvlrOther, now);
                sec.KvlrOtherChevron.BeginAnimation(RotateTransform.AngleProperty, Anim(null, now ? 180 : 0, 180));
                AutomationProperties.SetItemStatus(btn, now ? "open" : "closed");
                if (now) prefs.Add("set-other:" + sec.Group); else prefs.Remove("set-other:" + sec.Group);
                Prefs.Save(prefs);
            };
            sec.KvlrOtherFold = new StackPanel();
            sec.KvlrOtherRule = new Border { Height = 1, Background = R("Line") };
            sec.KvlrOtherFold.Children.Add(sec.KvlrOtherRule);
            sec.KvlrOtherFold.Children.Add(btn);
            Show(sec.KvlrOther, open);
            body.Children.Add(sec.KvlrOtherFold);
            body.Children.Add(sec.KvlrOther);
        }

        static bool KvlrOffValue(object v)
        {
            if (v is bool) return !(bool)v;
            if (IsNumber(v)) return Same(v, 0);
            var s = v as string;
            return s == "off" || s == "none";
        }

        /// <summary>RefreshSettings, after the rows are updated: which rows are Other (when due), then the lines between
        /// rows and the Other settings count. value: a setting's current value.</summary>
        void KvlrOtherRefresh(System.Func<SettingSpec, object> value)
        {
            if (kvlrSplitDue && settingSpecs != null)
            {
                kvlrSplitDue = false;
                foreach (var sec in settingSections)
                {
                    if (sec.KvlrMain == null) continue;
                    var other = new HashSet<string>();
                    foreach (var r in sec.Rows)  // spec order: a setting comes after the one it applies with
                    {
                        bool greyed = r.Note.Visibility == Visibility.Visible;
                        bool follows = r.Spec.AppliesKey != null && other.Contains(r.Spec.AppliesKey);
                        if (greyed || follows || KvlrOffValue(value(r.Spec))) other.Add(r.Spec.Key);
                    }
                    sec.KvlrMain.Children.Clear();
                    sec.KvlrOther.Children.Clear();
                    foreach (var r in sec.Rows)
                    {
                        r.KvlrOther = other.Contains(r.Spec.Key);
                        var panel = r.KvlrOther ? sec.KvlrOther : sec.KvlrMain;
                        if (r.Rule == null) r.Rule = Rule();
                        panel.Children.Add(r.Rule);
                        panel.Children.Add(r.Element);
                    }
                }
            }
            foreach (var sec in settingSections)
            {
                if (sec.KvlrMain == null) { FixRules(sec.Rows); continue; }
                var main = sec.Rows.Where(r => !r.KvlrOther).ToList();
                var rest = sec.Rows.Where(r => r.KvlrOther).ToList();
                FixRules(main);
                FixRules(rest);
                // the first row showing in each panel has no line above it (FixRules), except Other's, under its fold
                int n = rest.Count(r => r.Element.Visibility == Visibility.Visible);
                bool anyMain = main.Any(r => r.Element.Visibility == Visibility.Visible);
                sec.KvlrOtherLabel.Text = "Other settings (" + n + ")";
                Show(sec.KvlrOtherFold, n > 0);
                Show(sec.KvlrOtherRule, anyMain);
                Show(sec.KvlrMain, anyMain);
                AutomationProperties.SetName((Button)sec.KvlrOtherFold.Children[1], "Other settings, " + n);
            }
        }
    }
}
