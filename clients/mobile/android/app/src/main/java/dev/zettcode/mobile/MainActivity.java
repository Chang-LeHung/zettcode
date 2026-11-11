package dev.zettcode.mobile;

import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebBackForwardList;
import android.webkit.WebHistoryItem;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;

import com.getcapacitor.BridgeActivity;

import java.util.Objects;

public class MainActivity extends BridgeActivity {
    private String lastBackUrl = "";
    private long lastBackAt = 0L;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getOnBackPressedDispatcher().addCallback(
                this,
                new OnBackPressedCallback(true) {
                    @Override
                    public void handleOnBackPressed() {
                        WebView view = getBridge() == null ? null : getBridge().getWebView();
                        if (view == null) {
                            leave();
                            return;
                        }
                        Uri current = Uri.parse(view.getUrl() == null ? "" : view.getUrl());
                        String local = getBridge().getLocalUrl();
                        Uri picker = Uri.parse(local == null ? "http://localhost" : local);
                        if (sameOrigin(current, picker)) {
                            leave();
                            return;
                        }
                        // A gesture on a gateway page walks that page's own history, like its < arrow, and never
                        // signs the reader out to the picker. At the root, a second Back leaves the app instead.
                        WebBackForwardList history = view.copyBackForwardList();
                        int index = history == null ? -1 : history.getCurrentIndex();
                        if (index > 0) {
                            WebHistoryItem previous = history.getItemAtIndex(index - 1);
                            Uri target = Uri.parse(previous == null || previous.getUrl() == null ? "" : previous.getUrl());
                            boolean web = "http".equals(target.getScheme()) || "https".equals(target.getScheme());
                            if (web && !sameOrigin(target, picker)) {
                                lastBackUrl = "";
                                view.goBack();
                                return;
                            }
                        }
                        long now = SystemClock.elapsedRealtime();
                        if (current.toString().equals(lastBackUrl) && now - lastBackAt < 2000L) {
                            leave();
                            return;
                        }
                        lastBackUrl = current.toString();
                        lastBackAt = now;
                        Toast.makeText(
                                        MainActivity.this,
                                        "Press Back again to leave ZettCode",
                                        Toast.LENGTH_SHORT)
                                .show();
                    }

                    private void leave() {
                        setEnabled(false);
                        getOnBackPressedDispatcher().onBackPressed();
                    }
                });
    }

    private static boolean sameOrigin(Uri first, Uri second) {
        return first != null
                && second != null
                && Objects.equals(first.getScheme(), second.getScheme())
                && Objects.equals(first.getHost(), second.getHost())
                && portOf(first) == portOf(second);
    }

    private static int portOf(Uri uri) {
        if (uri.getPort() != -1) return uri.getPort();
        if ("http".equals(uri.getScheme())) return 80;
        if ("https".equals(uri.getScheme())) return 443;
        return -1;
    }
}
