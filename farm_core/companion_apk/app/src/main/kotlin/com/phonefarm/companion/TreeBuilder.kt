package com.phonefarm.companion

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * Обход дерева AccessibilityNodeInfo в плоский JSON-список видимых узлов.
 *
 * Плоский список (а не вложенное дерево) сознательно: транспорт на ПК
 * (brain/a11y_transport.py) сопоставляет узлы так же, как parse_nodes() парсит
 * XML uiautomator — по text/desc/rid и bounds. Плоский список = 1:1 замена.
 */
object TreeBuilder {

    private const val MAX_NODES = 4000       // страховка от гигантских webview-деревьев
    private const val MAX_DEPTH = 60

    fun build(root: AccessibilityNodeInfo?): JSONObject {
        val nodes = JSONArray()
        if (root != null) {
            val rect = Rect()
            walk(root, nodes, 0, rect)
        }
        val out = JSONObject()
        out.put("nodes", nodes)
        out.put("count", nodes.length())
        return out
    }

    private fun walk(node: AccessibilityNodeInfo?, out: JSONArray, depth: Int, rect: Rect) {
        if (node == null || depth > MAX_DEPTH || out.length() >= MAX_NODES) return

        node.getBoundsInScreen(rect)
        val text = node.text?.toString() ?: ""
        val desc = node.contentDescription?.toString() ?: ""
        val rid = node.viewIdResourceName ?: ""
        val cls = node.className?.toString() ?: ""

        // отдаём узел, если он несёт что-то полезное для сопоставления/клика:
        // текст, описание, id, либо кликабелен/фокусируем (иначе — мусорные контейнеры).
        val useful = text.isNotEmpty() || desc.isNotEmpty() || rid.isNotEmpty() ||
                node.isClickable || node.isEditable || node.isFocusable
        val visible = rect.width() > 0 && rect.height() > 0

        if (useful && visible) {
            val n = JSONObject()
            n.put("resource_id", rid)
            n.put("text", text)
            n.put("content_desc", desc)
            n.put("class_name", cls)
            val b = JSONObject()
            b.put("left", rect.left)
            b.put("top", rect.top)
            b.put("right", rect.right)
            b.put("bottom", rect.bottom)
            n.put("bounds", b)
            n.put("clickable", node.isClickable)
            n.put("enabled", node.isEnabled)
            n.put("focused", node.isFocused)
            n.put("editable", node.isEditable)
            n.put("scrollable", node.isScrollable)
            out.put(n)
        }

        val count = node.childCount
        for (i in 0 until count) {
            val child = node.getChild(i)
            if (child != null) {
                walk(child, out, depth + 1, rect)
                child.recycle()
            }
        }
    }
}
