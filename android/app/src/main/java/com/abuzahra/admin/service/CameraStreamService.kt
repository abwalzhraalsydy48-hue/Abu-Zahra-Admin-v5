package com.abuzahra.admin.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.hardware.camera2.params.StreamConfigurationMap
import android.media.Image
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Size
import android.view.Surface
import androidx.core.app.NotificationCompat
import com.abuzahra.admin.App
import com.abuzahra.admin.MainActivity
import com.abuzahra.admin.R
import com.abuzahra.admin.network.ApiService
import com.abuzahra.admin.utils.DeviceInfo
import kotlinx.coroutines.*
import okio.ByteString
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.nio.ByteBuffer
import java.util.concurrent.TimeUnit

class CameraStreamService : Service() {
    
    private var cameraDevice: CameraDevice? = null
    private var cameraCaptureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var backgroundThread: HandlerThread? = null
    private var backgroundHandler: Handler? = null
    
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private lateinit var apiService: ApiService
    private var webSocket: WebSocket? = null
    private var cameraId: Int = 0
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
    
    override fun onCreate() {
        super.onCreate()
        apiService = ApiService.getInstance(this)
        startForegroundNotification()
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        cameraId = intent?.getIntExtra("camera_id", 0) ?: 0
        startBackgroundThread()
        connectWebSocket()
        openCamera()
        return START_STICKY
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    private fun startForegroundNotification() {
        val pendingIntent = PendingIntent.getActivity(
            this,
            3,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        
        val notification = NotificationCompat.Builder(this, App.CHANNEL_ID_CAMERA)
            .setContentTitle("Camera Service")
            .setContentText("Camera streaming active")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        
        startForeground(3, notification)
    }
    
    private fun startBackgroundThread() {
        backgroundThread = HandlerThread("CameraBackground").also { it.start() }
        backgroundHandler = Handler(backgroundThread!!.looper)
    }
    
    private fun connectWebSocket() {
        val deviceId = DeviceInfo.getDeviceId(this)
        val request = Request.Builder()
            .url(apiService.getWebSocketUrl(deviceId) + "/camera")
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }
        })
    }
    
    private fun openCamera() {
        val manager = getSystemService(CAMERA_SERVICE) as CameraManager
        val cameraIdStr = getCameraId(manager, cameraId)
        
        try {
            manager.openCamera(cameraIdStr, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    cameraDevice = camera
                    createCaptureSession()
                }
                
                override fun onDisconnected(camera: CameraDevice) {
                    camera.close()
                    cameraDevice = null
                }
                
                override fun onError(camera: CameraDevice, error: Int) {
                    camera.close()
                    cameraDevice = null
                }
            }, backgroundHandler)
        } catch (e: SecurityException) {
            e.printStackTrace()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    private fun getCameraId(manager: CameraManager, facing: Int): String {
        for (id in manager.cameraIdList) {
            val characteristics = manager.getCameraCharacteristics(id)
            val lensFacing = characteristics.get(CameraCharacteristics.LENS_FACING)
            if (lensFacing == if (facing == 0) CameraCharacteristics.LENS_FACING_BACK else CameraCharacteristics.LENS_FACING_FRONT) {
                return id
            }
        }
        return "0"
    }
    
    private fun createCaptureSession() {
        val manager = getSystemService(CAMERA_SERVICE) as CameraManager
        val characteristics = manager.getCameraCharacteristics(cameraDevice?.id ?: "0")
        val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val sizes = map?.getOutputSizes(ImageFormat.JPEG)
        val size = sizes?.firstOrNull() ?: Size(640, 480)
        
        imageReader = ImageReader.newInstance(size.width, size.height, ImageFormat.JPEG, 2)
        imageReader?.setOnImageAvailableListener({ reader ->
            val image = reader.acquireLatestImage()
            image?.let {
                processImage(it)
                it.close()
            }
        }, backgroundHandler)
        
        try {
            cameraDevice?.createCaptureSession(
                listOf(imageReader?.surface),
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        cameraCaptureSession = session
                        startPreview()
                    }
                    
                    override fun onConfigureFailed(session: CameraCaptureSession) {
                        // Handle error
                    }
                },
                backgroundHandler
            )
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    private fun startPreview() {
        val captureRequestBuilder = cameraDevice?.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
        captureRequestBuilder?.addTarget(imageReader?.surface!!)
        
        cameraCaptureSession?.setRepeatingRequest(
            captureRequestBuilder?.build()!!,
            null,
            backgroundHandler
        )
    }
    
    private fun processImage(image: Image) {
        val buffer = image.planes[0].buffer
        val bytes = ByteArray(buffer.remaining())
        buffer.get(bytes)
        
        // Send via WebSocket
        webSocket?.send(ByteString.of(*bytes))
    }
    
    override fun onDestroy() {
        super.onDestroy()
        cameraCaptureSession?.close()
        cameraDevice?.close()
        imageReader?.close()
        backgroundThread?.quitSafely()
        webSocket?.close(1000, null)
        serviceScope.cancel()
    }
}
