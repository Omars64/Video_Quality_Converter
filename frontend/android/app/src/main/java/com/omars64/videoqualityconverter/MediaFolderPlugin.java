package com.omars64.videoqualityconverter;

import android.Manifest;
import android.content.ContentValues;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

@CapacitorPlugin(name = "MediaFolder", permissions = {
    @Permission(alias = "legacyStorage", strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE })
})
public class MediaFolderPlugin extends Plugin {
    @PluginMethod
    public void saveToDownloads(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q && getPermissionState("legacyStorage") != PermissionState.GRANTED) {
            requestPermissionForAlias("legacyStorage", call, "storagePermissionResult");
            return;
        }
        getBridge().execute(() -> save(call));
    }

    @PermissionCallback
    private void storagePermissionResult(PluginCall call) {
        if (getPermissionState("legacyStorage") != PermissionState.GRANTED) {
            call.reject("Android requires storage permission to save in Downloads on this version.");
            return;
        }
        saveToDownloads(call);
    }

    private void save(PluginCall call) {
        Uri destination = null;
        File legacyFile = null;
        try {
            String sourceUri = call.getString("sourceUri");
            if (sourceUri == null) throw new IllegalArgumentException("A completed download is required.");
            Uri parsed = Uri.parse(sourceUri);
            if (!"file".equals(parsed.getScheme())) throw new IllegalArgumentException("Invalid cache file.");
            File source = new File(parsed.getPath()).getCanonicalFile();
            String cacheRoot = getContext().getCacheDir().getCanonicalPath() + File.separator;
            if (!source.getPath().startsWith(cacheRoot) || !source.isFile() || source.length() == 0) {
                throw new IllegalArgumentException("Only a completed app download can be saved.");
            }
            String name = call.getString("name", "download").replaceAll("[\\\\/\\p{Cntrl}]", "_");
            if (name.isBlank() || name.equals(".") || name.equals("..")) name = "download";
            String mime = call.getString("mime", "application/octet-stream");
            OutputStream output;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                values.put(MediaStore.MediaColumns.IS_PENDING, 1);
                destination = getContext().getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (destination == null) throw new IllegalStateException("Downloads storage is unavailable.");
                output = getContext().getContentResolver().openOutputStream(destination, "w");
            } else {
                File directory = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("Downloads storage is unavailable.");
                int dot = name.lastIndexOf('.');
                for (int index = 1; index <= 10000; index++) {
                    String candidate = index == 1 ? name : dot > 0 ? name.substring(0, dot) + "-" + index + name.substring(dot) : name + "-" + index;
                    File file = new File(directory, candidate);
                    if (file.createNewFile()) { legacyFile = file; break; }
                }
                if (legacyFile == null) throw new IllegalStateException("Too many files with this name.");
                output = new FileOutputStream(legacyFile);
            }
            if (output == null) throw new IllegalStateException("Could not write the download.");
            long copied = 0;
            try (InputStream input = new FileInputStream(source); OutputStream out = output) {
                byte[] buffer = new byte[256 * 1024];
                int count;
                while ((count = input.read(buffer)) != -1) { out.write(buffer, 0, count); copied += count; }
            }
            if (copied != source.length()) throw new IllegalStateException("The saved file is incomplete.");
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.IS_PENDING, 0);
                if (getContext().getContentResolver().update(destination, values, null, null) != 1) {
                    throw new IllegalStateException("Could not publish the completed download.");
                }
            } else {
                MediaScannerConnection.scanFile(getContext(), new String[] { legacyFile.getPath() }, new String[] { mime }, null);
            }
            JSObject result = new JSObject();
            result.put("name", name);
            result.put("bytes", copied);
            call.resolve(result);
        } catch (Exception error) {
            if (destination != null) {
                try { getContext().getContentResolver().delete(destination, null, null); } catch (Exception ignored) { }
            }
            if (legacyFile != null) legacyFile.delete();
            call.reject("Could not save to Downloads: " + error.getMessage());
        }
    }
}
