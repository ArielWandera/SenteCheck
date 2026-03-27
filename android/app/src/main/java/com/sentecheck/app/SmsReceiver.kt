package com.sentecheck.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log

private const val TAG = "SmsReceiver"

/**
 * SmsReceiver — BroadcastReceiver that fires on every incoming SMS.
 *
 * It passes each message through MobileMoneyFilter before forwarding.
 * Non-mobile-money SMS are dropped immediately — they never leave the device.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isNullOrEmpty()) return

        // Group PDUs by originating address into full message bodies
        val grouped = messages.groupBy { it.originatingAddress }

        for ((_, parts) in grouped) {
            val body = parts.joinToString("") { it.messageBody }
            val simSlot = parts.firstOrNull()?.indexOnIcc ?: 0

            if (!MobileMoneyFilter.isMobileMoneySms(body)) {
                Log.d(TAG, "Skipping non-mobile-money SMS")
                continue
            }

            Log.d(TAG, "Mobile money SMS detected — forwarding")
            SmsForwarder.forward(context, body, simSlot)
        }
    }
}
