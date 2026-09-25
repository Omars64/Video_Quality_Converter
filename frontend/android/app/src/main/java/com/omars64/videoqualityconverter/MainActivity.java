package com.omars64.videoqualityconverter;

import com.getcapacitor.BridgeActivity;
import android.os.Bundle;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MediaFolderPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
