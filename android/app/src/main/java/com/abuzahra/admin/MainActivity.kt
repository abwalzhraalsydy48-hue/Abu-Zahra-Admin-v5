package com.abuzahra.admin

import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.abuzahra.admin.manager.PermissionManager
import com.abuzahra.admin.manager.PreferenceManager
import com.abuzahra.admin.network.ApiService
import com.abuzahra.admin.service.CommandService
import com.abuzahra.admin.utils.DeviceInfo
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {
    
    private lateinit var etLinkCode: TextInputEditText
    private lateinit var btnLink: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvTitle: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var btnGrantPermissions: Button
    private lateinit var permissionManager: PermissionManager
    private lateinit var preferenceManager: PreferenceManager
    
    private val OVERLAY_PERMISSION_REQUEST_CODE = 1001
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        
        // Initialize PreferenceManager
        PreferenceManager.init(this)
        preferenceManager = PreferenceManager.getInstance()
        
        permissionManager = PermissionManager(this)
        
        initViews()
        checkPermissions()
    }
    
    private fun initViews() {
        etLinkCode = findViewById(R.id.etLinkCode)
        btnLink = findViewById(R.id.btnLink)
        tvStatus = findViewById(R.id.tvStatus)
        tvTitle = findViewById(R.id.tvTitle)
        progressBar = findViewById(R.id.progressBar)
        btnGrantPermissions = findViewById(R.id.btnGrantPermissions)
        
        // Check if already registered
        if (preferenceManager.isRegistered()) {
            showRegisteredState()
        } else {
            btnLink.setOnClickListener {
                val code = etLinkCode.text.toString().trim()
                if (code.length >= 6) {
                    linkDevice(code)
                } else {
                    Toast.makeText(this, getString(R.string.code_too_short), Toast.LENGTH_SHORT).show()
                }
            }
        }
        
        btnGrantPermissions.setOnClickListener {
            permissionManager.requestAllPermissions()
        }
    }
    
    private fun checkPermissions() {
        // Check overlay permission first
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            requestOverlayPermission()
            return
        }
        
        updatePermissionButton()
    }
    
    private fun requestOverlayPermission() {
        AlertDialog.Builder(this)
            .setTitle(R.string.permission_required)
            .setMessage(R.string.overlay_permission_message)
            .setPositiveButton(R.string.ok) { _, _ ->
                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")
                )
                startActivityForResult(intent, OVERLAY_PERMISSION_REQUEST_CODE)
            }
            .setCancelable(false)
            .show()
    }
    
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == OVERLAY_PERMISSION_REQUEST_CODE) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && Settings.canDrawOverlays(this)) {
                checkPermissions()
            } else {
                Toast.makeText(this, R.string.permission_required_msg, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }
    
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        permissionManager.onRequestPermissionsResult(requestCode, permissions, grantResults)
        updatePermissionButton()
        
        // If all permissions granted and registered, start service
        if (permissionManager.hasAllPermissions() && preferenceManager.isRegistered()) {
            startCommandService()
        }
    }
    
    private fun updatePermissionButton() {
        if (permissionManager.hasAllPermissions()) {
            btnGrantPermissions.visibility = View.GONE
        } else {
            btnGrantPermissions.visibility = View.VISIBLE
        }
    }
    
    private fun linkDevice(code: String) {
        showLoading(true)
        tvStatus.text = getString(R.string.linking_device)
        
        lifecycleScope.launch {
            try {
                val apiService = ApiService.getInstance(this@MainActivity)
                val result = withContext(Dispatchers.IO) {
                    apiService.verifyLinkCode(code)
                }
                
                showLoading(false)
                
                if (result.success) {
                    val deviceId = result.deviceId.ifEmpty { DeviceInfo.getDeviceId(this@MainActivity) }
                    preferenceManager.setDeviceId(deviceId)
                    preferenceManager.setRegistered(true)
                    showRegisteredState()
                    
                    // Start service
                    startCommandService()
                    
                    Toast.makeText(this@MainActivity, R.string.link_success, Toast.LENGTH_LONG).show()
                } else {
                    tvStatus.text = getString(R.string.link_failed, result.error)
                    Toast.makeText(this@MainActivity, result.error, Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                showLoading(false)
                tvStatus.text = getString(R.string.error_message, e.message)
                Toast.makeText(this@MainActivity, getString(R.string.connection_error, e.message), Toast.LENGTH_LONG).show()
            }
        }
    }
    
    private fun showLoading(show: Boolean) {
        progressBar.visibility = if (show) View.VISIBLE else View.GONE
        btnLink.isEnabled = !show
        etLinkCode.isEnabled = !show
    }
    
    private fun showRegisteredState() {
        etLinkCode.visibility = View.GONE
        btnLink.visibility = View.GONE
        tvTitle.text = getString(R.string.device_linked)
        tvStatus.text = getString(R.string.device_id_display, preferenceManager.getDeviceId())
        tvStatus.visibility = View.VISIBLE
        progressBar.visibility = View.GONE
        
        // If permissions granted, start service
        if (permissionManager.hasAllPermissions()) {
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
    }
    
    override fun onResume() {
        super.onResume()
        // Re-check overlay permission when returning to app
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && Settings.canDrawOverlays(this)) {
            updatePermissionButton()
        }
    }
}
