package com.abuzahra.admin

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.abuzahra.admin.manager.PermissionManager
import com.abuzahra.admin.service.CommandService

class MainActivity : AppCompatActivity() {
    
    private lateinit var permissionManager: PermissionManager
    private val OVERLAY_PERMISSION_REQUEST_CODE = 1001
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        
        permissionManager = PermissionManager(this)
        
        // Check and request overlay permission FIRST
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            requestOverlayPermission()
        } else {
            // Overlay permission granted, check other permissions
            checkAndRequestPermissions()
        }
    }
    
    private fun requestOverlayPermission() {
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:$packageName")
        )
        startActivityForResult(intent, OVERLAY_PERMISSION_REQUEST_CODE)
    }
    
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == OVERLAY_PERMISSION_REQUEST_CODE) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "Overlay permission granted", Toast.LENGTH_SHORT).show()
                checkAndRequestPermissions()
            } else {
                Toast.makeText(this, "Overlay permission is required for the app to work", Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }
    
    private fun checkAndRequestPermissions() {
        // Check for battery optimization
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val powerManager = getSystemService(POWER_SERVICE) as android.os.PowerManager
            if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                intent.data = Uri.parse("package:$packageName")
                startActivity(intent)
            }
        }
        
        // Check and request other permissions
        if (!permissionManager.hasAllPermissions()) {
            permissionManager.requestAllPermissions()
        } else {
            startCommandService()
        }
    }
    
    private fun startCommandService() {
        val intent = Intent(this, CommandService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        Toast.makeText(this, "Service started", Toast.LENGTH_SHORT).show()
    }
    
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        permissionManager.onRequestPermissionsResult(requestCode, permissions, grantResults)
    }
    
    override fun onResume() {
        super.onResume()
        // Only start service if all permissions are granted
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)) {
            if (permissionManager.hasAllPermissions()) {
                startCommandService()
            }
        }
    }
}
