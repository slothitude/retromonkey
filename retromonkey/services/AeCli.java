import java.io.*;
import java.util.*;

import com.global.iop.api.*;
import com.global.iop.util.*;
import com.aliexpress.open.request.*;
import com.aliexpress.open.response.*;

/**
 * Thin CLI wrapper for AliExpress IOP SDK.
 * Reads JSON from stdin: {"action": "...", "app_key": "...", "app_secret": "...", "params": {...}, "access_token": "..."}
 * Prints raw JSON response body to stdout, errors to stderr.
 */
public class AeCli {

    static final String SERVER_URL = "https://api-sg.aliexpress.com";

    public static void main(String[] args) throws Exception {
        // Read JSON from stdin
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            sb.append(line);
        }
        String input = sb.toString().trim();
        if (input.isEmpty()) {
            System.err.println("No input JSON provided on stdin");
            System.exit(1);
        }

        // Parse JSON manually (no external deps)
        Map<String, String> payload = parseSimpleJson(input);
        String action = payload.get("action");
        String appKey = payload.get("app_key");
        String appSecret = payload.get("app_secret");
        String accessToken = payload.get("access_token");
        String paramsJson = payload.get("params");

        if (appKey == null || appSecret == null || action == null) {
            System.err.println("Missing required fields: action, app_key, app_secret");
            System.exit(1);
        }

        IopClientImpl client = new IopClientImpl(SERVER_URL, appKey, appSecret);
        client.setNeedEnableLogger(false);

        Map<String, String> params = paramsJson != null ? parseSimpleJson(paramsJson) : new HashMap<>();

        try {
            String token = (accessToken != null && !accessToken.isEmpty()) ? accessToken : null;
            String responseBody;
            switch (action) {
                case "affiliate_search":
                    responseBody = affiliateSearch(client, params, token);
                    break;
                case "affiliate_detail":
                    responseBody = affiliateDetail(client, params, token);
                    break;
                case "affiliate_hotproduct":
                    responseBody = affiliateHotproduct(client, params, token);
                    break;
                default:
                    System.err.println("Unknown action: " + action);
                    System.exit(1);
                    return;
            }
            System.out.println(responseBody);
        } catch (ApiException e) {
            System.err.println("API error: " + e.getErrorCode() + " - " + e.getMessage());
            System.exit(1);
        } catch (Exception e) {
            System.err.println("Error: " + e.getClass().getName() + " - " + e.getMessage());
            e.printStackTrace(System.err);
            System.exit(1);
        }
    }

    static String affiliateSearch(IopClientImpl client, Map<String, String> params, String accessToken) throws Exception {
        AliexpressAffiliateProductQueryRequest req = new AliexpressAffiliateProductQueryRequest();
        req.setKeywords(params.get("keywords"));
        req.setCategoryIds(params.get("category_ids"));
        req.setFields(params.get("fields"));
        req.setTargetCurrency(params.get("target_currency"));
        req.setTargetLanguage(params.get("target_language"));
        req.setShipToCountry(params.get("ship_to_country"));
        req.setSort(params.get("sort"));
        req.setPlatformProductType(params.get("platform_product_type"));
        req.setPromotionName(params.get("promotion_name"));
        req.setDeliveryDays(params.get("delivery_days"));

        String pageSize = params.get("page_size");
        if (pageSize != null) req.setPageSize(Long.parseLong(pageSize));

        String pageNo = params.get("page_no");
        if (pageNo != null) req.setPageNo(Long.parseLong(pageNo));

        String minPrice = params.get("min_sale_price");
        if (minPrice != null) req.setMinSalePrice(Long.parseLong(minPrice));

        String maxPrice = params.get("max_sale_price");
        if (maxPrice != null) req.setMaxSalePrice(Long.parseLong(maxPrice));

        AliexpressAffiliateProductQueryResponse resp = accessToken != null ? client.execute(req, accessToken) : client.execute(req);
        if (!resp.isSuccess()) {
            throw new ApiException(resp.getGopErrorCode(), resp.getGopErrorMessage());
        }
        return resp.getGopResponseBody();
    }

    static String affiliateDetail(IopClientImpl client, Map<String, String> params, String accessToken) throws Exception {
        AliexpressAffiliateProductdetailGetRequest req = new AliexpressAffiliateProductdetailGetRequest();
        req.setProductIds(params.get("product_ids"));
        req.setFields(params.get("fields"));
        req.setTargetCurrency(params.get("target_currency"));
        req.setTargetLanguage(params.get("target_language"));
        req.setCountry(params.get("country"));
        req.setTrackingId(params.get("tracking_id"));

        AliexpressAffiliateProductdetailGetResponse resp = accessToken != null ? client.execute(req, accessToken) : client.execute(req);
        if (!resp.isSuccess()) {
            throw new ApiException(resp.getGopErrorCode(), resp.getGopErrorMessage());
        }
        return resp.getGopResponseBody();
    }

    static String affiliateHotproduct(IopClientImpl client, Map<String, String> params, String accessToken) throws Exception {
        AliexpressAffiliateHotproductQueryRequest req = new AliexpressAffiliateHotproductQueryRequest();
        req.setKeywords(params.get("keywords"));
        req.setCategoryIds(params.get("category_ids"));
        req.setFields(params.get("fields"));
        req.setTargetCurrency(params.get("target_currency"));
        req.setTargetLanguage(params.get("target_language"));
        req.setShipToCountry(params.get("ship_to_country"));
        req.setSort(params.get("sort"));
        req.setPlatformProductType(params.get("platform_product_type"));
        req.setPromotionName(params.get("promotion_name"));
        req.setDeliveryDays(params.get("delivery_days"));

        String pageSize = params.get("page_size");
        if (pageSize != null) req.setPageSize(Long.parseLong(pageSize));

        String pageNo = params.get("page_no");
        if (pageNo != null) req.setPageNo(Long.parseLong(pageNo));

        String minPrice = params.get("min_sale_price");
        if (minPrice != null) req.setMinSalePrice(Long.parseLong(minPrice));

        String maxPrice = params.get("max_sale_price");
        if (maxPrice != null) req.setMaxSalePrice(Long.parseLong(maxPrice));

        AliexpressAffiliateHotproductQueryResponse resp = accessToken != null ? client.execute(req, accessToken) : client.execute(req);
        if (!resp.isSuccess()) {
            throw new ApiException(resp.getGopErrorCode(), resp.getGopErrorMessage());
        }
        return resp.getGopResponseBody();
    }

    /**
     * Minimal JSON parser for flat string maps. Handles:
     * - Nested JSON as string values (params field)
     * - Simple key-value pairs
     * - String values only (all output as String)
     */
    static Map<String, String> parseSimpleJson(String json) {
        Map<String, String> result = new LinkedHashMap<>();
        json = json.trim();
        if (!json.startsWith("{") || !json.endsWith("}")) {
            return result;
        }
        // Remove outer braces
        String inner = json.substring(1, json.length() - 1);
        // Parse key-value pairs handling nested objects
        int depth = 0;
        StringBuilder current = new StringBuilder();
        String currentKey = null;
        boolean inString = false;
        char prevChar = 0;

        for (int i = 0; i < inner.length(); i++) {
            char c = inner.charAt(i);

            if (c == '"' && prevChar != '\\') {
                inString = !inString;
            }

            if (!inString) {
                if (c == '{' || c == '[') {
                    depth++;
                } else if (c == '}' || c == ']') {
                    depth--;
                } else if (c == ':' && depth == 0 && currentKey == null) {
                    currentKey = current.toString().trim().replace("\"", "");
                    current = new StringBuilder();
                    continue;
                } else if (c == ',' && depth == 0 && currentKey != null) {
                    String val = current.toString().trim();
                    if (val.startsWith("\"") && val.endsWith("\"")) {
                        val = val.substring(1, val.length() - 1);
                    }
                    result.put(currentKey, val);
                    currentKey = null;
                    current = new StringBuilder();
                    continue;
                }
            }

            if (c != ':' || (depth == 0 && currentKey == null) || inString || depth > 0) {
                current.append(c);
            }
            prevChar = c;
        }

        // Last pair
        if (currentKey != null) {
            String val = current.toString().trim();
            // Strip surrounding quotes from values
            if (val.startsWith("\"") && val.endsWith("\"")) {
                val = val.substring(1, val.length() - 1);
            }
            result.put(currentKey, val);
        }

        return result;
    }
}
