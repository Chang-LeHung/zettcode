package dev.zettcode.mobile;

import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebView;

import androidx.activity.OnBackPressedCallback;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
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
                        boolean onPicker = current.getScheme() != null
                                && current.getScheme().equals(picker.getScheme())
                                && current.getHost() != null
                                && current.getHost().equals(picker.getHost())
                                && current.getPort() == picker.getPort();
                        if (!onPicker) {
                            // Back from a gateway page is the server list; the page's own back arrow walks its sections.
                            view.loadUrl(local == null ? "http://localhost/" : local);
                            return;
                        }
                        leave();
                    }

                    private void leave() {
                        setEnabled(false);
                        getOnBackPressedDispatcher().onBackPressed();
                    }
                });
    }
}
