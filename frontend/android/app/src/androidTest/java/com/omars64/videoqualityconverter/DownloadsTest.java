package com.omars64.videoqualityconverter;

import static org.junit.Assert.*;
import android.content.Context;
import android.net.Uri;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.filters.SdkSuppress;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
@SdkSuppress(minSdkVersion = 29)
public class DownloadsTest {
    static class ResultCall extends PluginCall {
        JSObject result;
        String error;
        ResultCall(JSObject data) { super(null, "MediaFolder", "test", "saveToDownloads", data); }
        @Override public void resolve(JSObject value) { result = value; }
        @Override public void reject(String message) { error = message; }
    }

    @Test public void publicDownloadsPreservesBytesAndDoesNotOverwrite() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        MediaFolderPlugin plugin = new MediaFolderPlugin() {
            @Override public Context getContext() { return context; }
        };
        File source = File.createTempFile("downloads-test-", ".bin", context.getCacheDir());
        byte[] bytes = new byte[300000];
        for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) (i % 251);
        try (FileOutputStream output = new FileOutputStream(source)) { output.write(bytes); }
        List<Uri> created = new ArrayList<>();
        try {
            for (int i = 0; i < 2; i++) {
                JSObject data = new JSObject();
                data.put("sourceUri", Uri.fromFile(source).toString());
                data.put("name", source.getName());
                data.put("mime", "application/octet-stream");
                ResultCall call = new ResultCall(data);
                plugin.save(call);
                assertNull(call.error);
                assertNotNull(call.result);
                Uri uri = Uri.parse(call.result.getString("uri"));
                created.add(uri);
                assertEquals(bytes.length, call.result.getLong("bytes"));
                try (InputStream input = context.getContentResolver().openInputStream(uri)) {
                    java.io.ByteArrayOutputStream copied = new java.io.ByteArrayOutputStream();
                    byte[] buffer = new byte[8192]; int count;
                    while ((count = input.read(buffer)) != -1) copied.write(buffer, 0, count);
                    assertTrue(Arrays.equals(bytes, copied.toByteArray()));
                }
            }
            assertNotEquals(created.get(0), created.get(1));
        } finally {
            for (Uri uri : created) context.getContentResolver().delete(uri, null, null);
            source.delete();
        }
    }

    @Test public void refusesFilesOutsideAppCache() {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        MediaFolderPlugin plugin = new MediaFolderPlugin() {
            @Override public Context getContext() { return context; }
        };
        JSObject data = new JSObject();
        data.put("sourceUri", "file:///sdcard/Download/unrelated-file.mp4");
        ResultCall call = new ResultCall(data);
        plugin.save(call);
        assertNull(call.result);
        assertNotNull(call.error);
    }
}
