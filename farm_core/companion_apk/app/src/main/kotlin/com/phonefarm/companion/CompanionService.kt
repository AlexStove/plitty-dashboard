package com.phonefarm.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * AccessibilityService + встроенный HTTP-сервер на 127.0.0.1:7070.
 *
 * Мост между ПК-мозгом фермы и телефоном: даёт push-скорость дерева a11y,
 * клики по resource_id (без промахов по координатам) и ввод текста через
 * ACTION_SET_TEXT (эмодзи/кириллица/спецсимволы без глюков `input text`).
 *
 * Стартует автоматически при включении службы доступности (onServiceConnected),
 * останавливается при выключении (onDestroy).
 */
class CompanionService : AccessibilityService() {

    companion object {
        const val TAG = "A11YCompanion"
        const val VERSION = "1.0"
        const val PORT = 7070

        // Текущий живой экземпляр — HTTP-поток дёргает действия через него.
        @Volatile
        var instance: CompanionService? = null
    }

    private var server: HttpServer? = null
    private val main = Handler(Looper.getMainLooper())

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        startServer()
        Log.i(TAG, "service connected, http on 127.0.0.1:$PORT")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Событий не обрабатываем активно — дерево тянется по запросу /tree.
        // Подписка на typeWindowContentChanged держит окно «горячим» для быстрого чтения.
    }

    override fun onInterrupt() {
        Log.w(TAG, "onInterrupt")
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        stopServer()
        instance = null
        Log.i(TAG, "service unbound")
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        stopServer()
        instance = null
        super.onDestroy()
    }

    private fun startServer() {
        if (server != null) return
        try {
            server = HttpServer().also { it.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false) }
            Log.i(TAG, "http server started")
        } catch (e: Exception) {
            Log.e(TAG, "http start failed: ${e.message}", e)
            server = null
        }
    }

    private fun stopServer() {
        try {
            server?.stop()
        } catch (e: Exception) {
            Log.w(TAG, "http stop error: ${e.message}")
        }
        server = null
    }

    // ==================== Accessibility actions ====================

    /** Найти узел по resource_id. Сначала точный byViewId, затем суффикс-матч по дереву. */
    private fun findById(nodeId: String): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        try {
            val exact = root.findAccessibilityNodeInfosByViewId(nodeId)
            if (exact != null && exact.isNotEmpty()) {
                // отдаём первый видимый и enabled, иначе первый
                val best = exact.firstOrNull { it.isVisibleToUser && it.isEnabled } ?: exact[0]
                return best
            }
        } catch (_: Exception) {
        }
        // fallback: суффикс id / точное совпадение text|content-desc
        return bfsMatch(root, nodeId)
    }

    private fun bfsMatch(root: AccessibilityNodeInfo, key: String): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var scanned = 0
        while (queue.isNotEmpty() && scanned < 4000) {
            val n = queue.removeFirst()
            scanned++
            val rid = n.viewIdResourceName ?: ""
            val txt = n.text?.toString() ?: ""
            val desc = n.contentDescription?.toString() ?: ""
            if (rid == key || rid.endsWith("/$key") || (key.isNotEmpty() && (txt == key || desc == key))) {
                return n
            }
            for (i in 0 until n.childCount) {
                n.getChild(i)?.let { queue.add(it) }
            }
        }
        return null
    }

    /** Клик по узлу: если сам не clickable — поднимаемся к кликабельному предку. */
    fun clickNode(nodeId: String): Boolean {
        var node = findById(nodeId) ?: return false
        var target: AccessibilityNodeInfo? = node
        while (target != null && !target.isClickable) {
            target = target.parent
        }
        val hit = target ?: node
        return hit.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    /** Ввод текста в поле по resource_id через ACTION_SET_TEXT (без глюков input text). */
    fun setText(nodeId: String, text: String): Boolean {
        val node = findById(nodeId) ?: return false
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    /** Тап по координате через жест (не зависит от resource_id). */
    fun tapXY(x: Int, y: Int): Boolean {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()); lineTo(x.toFloat(), y.toFloat()) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 60)
        return dispatchBlocking(GestureDescription.Builder().addStroke(stroke).build())
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean {
        val path = Path().apply { moveTo(x1.toFloat(), y1.toFloat()); lineTo(x2.toFloat(), y2.toFloat()) }
        val dur = durationMs.coerceIn(1, 60000)
        val stroke = GestureDescription.StrokeDescription(path, 0, dur)
        return dispatchBlocking(GestureDescription.Builder().addStroke(stroke).build())
    }

    /** dispatchGesture синхронно: колбэк на главном потоке, ждём латчем (HTTP-поток блокируется). */
    private fun dispatchBlocking(gesture: GestureDescription): Boolean {
        val latch = CountDownLatch(1)
        val ok = booleanArrayOf(false)
        main.post {
            val dispatched = dispatchGesture(gesture, object : GestureResultCallback() {
                override fun onCompleted(g: GestureDescription?) {
                    ok[0] = true; latch.countDown()
                }

                override fun onCancelled(g: GestureDescription?) {
                    ok[0] = false; latch.countDown()
                }
            }, null)
            if (!dispatched) latch.countDown()
        }
        latch.await(8, TimeUnit.SECONDS)
        return ok[0]
    }

    /** Скриншот через AccessibilityService.takeScreenshot (API 30+). Возврат PNG или null. */
    fun screenshotPng(): ByteArray? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val latch = CountDownLatch(1)
        val holder = arrayOfNulls<ByteArray>(1)
        try {
            takeScreenshot(
                android.view.Display.DEFAULT_DISPLAY,
                Executors.newSingleThreadExecutor(),
                object : TakeScreenshotCallback {
                    override fun onSuccess(result: ScreenshotResult) {
                        try {
                            val bmp = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                            if (bmp != null) {
                                val bos = ByteArrayOutputStream()
                                bmp.copy(Bitmap.Config.ARGB_8888, false)
                                    .compress(Bitmap.CompressFormat.PNG, 100, bos)
                                holder[0] = bos.toByteArray()
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "screenshot encode: ${e.message}")
                        } finally {
                            result.hardwareBuffer.close()
                            latch.countDown()
                        }
                    }

                    override fun onFailure(errorCode: Int) {
                        Log.w(TAG, "screenshot failed: $errorCode")
                        latch.countDown()
                    }
                })
        } catch (e: Exception) {
            Log.e(TAG, "takeScreenshot: ${e.message}")
            return null
        }
        latch.await(5, TimeUnit.SECONDS)
        return holder[0]
    }

    // ==================== HTTP ====================

    private inner class HttpServer : NanoHTTPD("127.0.0.1", PORT) {

        override fun serve(session: IHTTPSession): Response {
            return try {
                route(session)
            } catch (e: Exception) {
                Log.e(TAG, "serve error ${session.uri}: ${e.message}", e)
                jsonResp(Response.Status.INTERNAL_ERROR, errObj(e.message ?: "internal"))
            }
        }

        private fun route(session: IHTTPSession): Response {
            val uri = session.uri
            val method = session.method
            return when {
                uri == "/ping" -> {
                    val o = JSONObject().put("ok", true).put("version", VERSION)
                    jsonResp(Response.Status.OK, o)
                }

                uri == "/tree" -> {
                    val root = rootInActiveWindow
                    val tree = TreeBuilder.build(root)
                    root?.recycle()
                    jsonResp(Response.Status.OK, tree)
                }

                uri == "/tap" && method == Method.POST -> {
                    val body = readBody(session)
                    val ok = if (body.has("node_id")) {
                        clickNode(body.getString("node_id"))
                    } else if (body.has("x") && body.has("y")) {
                        tapXY(body.getInt("x"), body.getInt("y"))
                    } else {
                        return jsonResp(Response.Status.BAD_REQUEST, errObj("need node_id or x/y"))
                    }
                    resultResp(ok, if (ok) null else "action_failed")
                }

                uri == "/type" && method == Method.POST -> {
                    val body = readBody(session)
                    if (!body.has("node_id") || !body.has("text")) {
                        return jsonResp(Response.Status.BAD_REQUEST, errObj("need node_id and text"))
                    }
                    val ok = setText(body.getString("node_id"), body.getString("text"))
                    resultResp(ok, if (ok) null else "set_text_failed")
                }

                uri == "/swipe" && method == Method.POST -> {
                    val body = readBody(session)
                    val ok = swipe(
                        body.getInt("x1"), body.getInt("y1"),
                        body.getInt("x2"), body.getInt("y2"),
                        body.optLong("duration_ms", 300)
                    )
                    resultResp(ok, if (ok) null else "gesture_failed")
                }

                uri == "/screenshot" -> {
                    val png = screenshotPng()
                    if (png == null) {
                        newFixedLengthResponse(
                            Response.Status.NOT_FOUND, "text/plain", "screenshot unavailable"
                        )
                    } else {
                        newFixedLengthResponse(
                            Response.Status.OK, "image/png",
                            ByteArrayInputStream(png), png.size.toLong()
                        )
                    }
                }

                else -> jsonResp(Response.Status.NOT_FOUND, errObj("no route: $method $uri"))
            }
        }

        private fun readBody(session: IHTTPSession): JSONObject {
            val files = HashMap<String, String>()
            session.parseBody(files)
            val raw = files["postData"] ?: "{}"
            return if (raw.isBlank()) JSONObject() else JSONObject(raw)
        }

        private fun jsonResp(status: Response.Status, obj: JSONObject): Response {
            val r = newFixedLengthResponse(status, "application/json", obj.toString())
            r.addHeader("Cache-Control", "no-store")
            return r
        }

        private fun resultResp(ok: Boolean, error: String?): Response {
            val o = JSONObject().put("ok", ok)
            if (error != null) o.put("error", error)
            return jsonResp(if (ok) Response.Status.OK else Response.Status.OK, o)
        }

        private fun errObj(msg: String) = JSONObject().put("ok", false).put("error", msg)
    }
}
