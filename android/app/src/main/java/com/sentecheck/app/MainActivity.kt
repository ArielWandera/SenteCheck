package com.sentecheck.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

private const val PREF_NAME = "sentecheck_prefs"
private const val KEY_TELEGRAM_ID = "telegram_id"
private const val KEY_WEBHOOK_SECRET = "webhook_secret"
private const val KEY_API_URL = "api_url"

class MainActivity : AppCompatActivity() {

    private lateinit var inputTelegramId: EditText
    private lateinit var inputWebhookSecret: EditText
    private lateinit var inputApiUrl: EditText
    private lateinit var btnConnect: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvPermissionStatus: TextView

    private val requestPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        val allGranted = grants.values.all { it }
        if (allGranted) {
            tvPermissionStatus.setText(R.string.permission_granted)
            tvPermissionStatus.setTextColor(getColor(android.R.color.holo_green_dark))
        } else {
            tvPermissionStatus.setText(R.string.permission_denied)
            tvPermissionStatus.setTextColor(getColor(android.R.color.holo_red_dark))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        inputTelegramId = findViewById(R.id.input_telegram_id)
        inputWebhookSecret = findViewById(R.id.input_webhook_secret)
        inputApiUrl = findViewById(R.id.input_api_url)
        btnConnect = findViewById(R.id.btn_connect)
        tvStatus = findViewById(R.id.tv_status)
        tvPermissionStatus = findViewById(R.id.tv_permission_status)

        loadSavedPrefs()
        checkAndRequestPermissions()

        btnConnect.setOnClickListener { onConnectClicked() }
    }

    private fun loadSavedPrefs() {
        val prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE)
        val savedTelegramId = prefs.getLong(KEY_TELEGRAM_ID, -1L)
        if (savedTelegramId > 0) {
            inputTelegramId.setText(savedTelegramId.toString())
        }
        val savedSecret = prefs.getString(KEY_WEBHOOK_SECRET, "") ?: ""
        if (savedSecret.isNotBlank()) {
            inputWebhookSecret.setText(savedSecret)
        }
        val savedUrl = prefs.getString(KEY_API_URL, BuildConfig.API_BASE_URL) ?: BuildConfig.API_BASE_URL
        inputApiUrl.setText(savedUrl)

        if (savedTelegramId > 0 && savedSecret.isNotBlank()) {
            tvStatus.setText(R.string.status_connected)
            tvStatus.setTextColor(getColor(android.R.color.holo_green_dark))
        }
    }

    private fun checkAndRequestPermissions() {
        val smsPermission = Manifest.permission.RECEIVE_SMS
        val readPermission = Manifest.permission.READ_SMS

        val allGranted = listOf(smsPermission, readPermission).all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }

        if (allGranted) {
            tvPermissionStatus.setText(R.string.permission_granted)
            tvPermissionStatus.setTextColor(getColor(android.R.color.holo_green_dark))
        } else {
            tvPermissionStatus.setText(R.string.permission_required)
            tvPermissionStatus.setTextColor(getColor(android.R.color.holo_orange_dark))
            requestPermissions.launch(arrayOf(smsPermission, readPermission))
        }
    }

    private fun onConnectClicked() {
        val telegramIdStr = inputTelegramId.text.toString().trim()
        val webhookSecret = inputWebhookSecret.text.toString().trim()
        val apiUrl = inputApiUrl.text.toString().trim()

        if (telegramIdStr.isBlank()) {
            inputTelegramId.error = getString(R.string.error_telegram_id_required)
            return
        }
        val telegramId = telegramIdStr.toLongOrNull()
        if (telegramId == null || telegramId <= 0) {
            inputTelegramId.error = getString(R.string.error_telegram_id_invalid)
            return
        }
        if (webhookSecret.isBlank()) {
            inputWebhookSecret.error = getString(R.string.error_secret_required)
            return
        }
        if (apiUrl.isBlank() || (!apiUrl.startsWith("https://") && !apiUrl.startsWith("http://"))) {
            inputApiUrl.error = getString(R.string.error_api_url_invalid)
            return
        }

        getSharedPreferences(PREF_NAME, MODE_PRIVATE).edit()
            .putLong(KEY_TELEGRAM_ID, telegramId)
            .putString(KEY_WEBHOOK_SECRET, webhookSecret)
            .putString(KEY_API_URL, apiUrl.trimEnd('/') + "/")
            .apply()

        tvStatus.setText(R.string.status_connected)
        tvStatus.setTextColor(getColor(android.R.color.holo_green_dark))
        tvStatus.visibility = View.VISIBLE
    }
}
