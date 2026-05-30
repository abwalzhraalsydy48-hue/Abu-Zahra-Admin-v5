package com.abuzahra.admin.utils

import android.content.Context
import android.os.Build
import android.os.Environment
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*

object FileHelper {
    
    fun getAppDirectory(context: Context): File {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            File(context.getExternalFilesDir(null), "abuzahra")
        } else {
            File(Environment.getExternalStorageDirectory(), "abuzahra")
        }.apply { if (!exists()) mkdirs() }
    }
    
    fun getRecordingsDirectory(context: Context): File {
        return File(getAppDirectory(context), "recordings").apply {
            if (!exists()) mkdirs()
        }
    }
    
    fun getImagesDirectory(context: Context): File {
        return File(getAppDirectory(context), "images").apply {
            if (!exists()) mkdirs()
        }
    }
    
    fun getFilesDirectory(context: Context): File {
        return File(getAppDirectory(context), "files").apply {
            if (!exists()) mkdirs()
        }
    }
    
    fun createTimestampFile(context: Context, type: String): File {
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val fileName = "${type}_$timestamp"
        return File(getFilesDirectory(context), fileName)
    }
    
    fun writeBytesToFile(file: File, data: ByteArray): Boolean {
        return try {
            FileOutputStream(file).use { fos ->
                fos.write(data)
            }
            true
        } catch (e: IOException) {
            e.printStackTrace()
            false
        }
    }
    
    fun deleteFile(file: File): Boolean {
        return if (file.exists()) {
            file.delete()
        } else {
            false
        }
    }
    
    fun getFileSize(file: File): Long {
        return if (file.exists()) file.length() else 0L
    }
    
    fun listFiles(directory: File): List<File> {
        return if (directory.exists() && directory.isDirectory) {
            directory.listFiles()?.toList() ?: emptyList()
        } else {
            emptyList()
        }
    }
    
    fun cleanupOldFiles(directory: File, maxAge: Long) {
        val now = System.currentTimeMillis()
        listFiles(directory).forEach { file ->
            if (now - file.lastModified() > maxAge) {
                file.delete()
            }
        }
    }
}
