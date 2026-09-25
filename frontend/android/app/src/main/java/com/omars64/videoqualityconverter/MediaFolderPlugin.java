package com.omars64.videoqualityconverter;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashSet;
import java.util.Set;

@CapacitorPlugin(name = "MediaFolder")
public class MediaFolderPlugin extends Plugin {
    @PluginMethod
    public void pickDirectory(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(call, intent, "directoryPicked");
    }

    @ActivityCallback
    private void directoryPicked(PluginCall call, ActivityResult result) {
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null || data.getData() == null) {
            call.reject("Folder selection canceled");
            return;
        }
        Uri uri = data.getData();
        try {
            int flags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            getContext().getContentResolver().takePersistableUriPermission(uri, flags);
            JSObject response = new JSObject();
            response.put("uri", uri.toString());
            call.resolve(response);
        } catch (Exception error) {
            call.reject("Could not use this folder: " + error.getMessage());
        }
    }

    @PluginMethod
    public void saveFile(PluginCall call) {
        String directoryUri = call.getString("directoryUri");
        String sourceUri = call.getString("sourceUri");
        String requestedName = call.getString("name", "download");
        String mime = call.getString("mime", "application/octet-stream");
        if (directoryUri == null || sourceUri == null) {
            call.reject("A save folder and source file are required.");
            return;
        }
        try {
            Uri tree = Uri.parse(directoryUri);
            if (!"content".equals(tree.getScheme()) || !DocumentsContract.isTreeUri(tree)) {
                throw new IllegalArgumentException("Select a valid device folder.");
            }
            File source = new File(Uri.parse(sourceUri).getPath()).getCanonicalFile();
            String cacheRoot = getContext().getCacheDir().getCanonicalPath() + File.separator;
            if (!source.getPath().startsWith(cacheRoot) || !source.isFile()) {
                throw new IllegalArgumentException("Only a completed app download can be saved.");
            }
            String name = requestedName.replaceAll("[\\\\/\\p{Cntrl}]", "_");
            if (name.isBlank()) name = "download";
            Uri parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree));
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree));
            Set<String> existing = new HashSet<>();
            try (Cursor cursor = getContext().getContentResolver().query(children, new String[] { DocumentsContract.Document.COLUMN_DISPLAY_NAME }, null, null, null)) {
                if (cursor != null) while (cursor.moveToNext()) existing.add(cursor.getString(0));
            }
            String filename = name;
            int dot = name.lastIndexOf('.');
            for (int index = 2; existing.contains(filename) && index < 1002; index++) {
                filename = dot > 0 ? name.substring(0, dot) + "-" + index + name.substring(dot) : name + "-" + index;
            }
            if (existing.contains(filename)) throw new IllegalStateException("Too many files with this name in the selected folder.");
            Uri destination = DocumentsContract.createDocument(getContext().getContentResolver(), parent, mime, filename);
            if (destination == null) throw new IllegalStateException("The selected folder refused the file.");
            try (InputStream in = new FileInputStream(source); OutputStream out = getContext().getContentResolver().openOutputStream(destination, "w")) {
                if (out == null) throw new IllegalStateException("The selected folder could not be written.");
                byte[] buffer = new byte[256 * 1024];
                int count;
                while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
            } catch (Exception error) {
                DocumentsContract.deleteDocument(getContext().getContentResolver(), destination);
                throw error;
            }
            JSObject response = new JSObject();
            response.put("name", filename);
            call.resolve(response);
        } catch (Exception error) {
            call.reject("Could not save to the selected folder: " + error.getMessage());
        }
    }
}
