from flask import Flask, request, jsonify
import ee

# Initialize Earth Engine (uses your provided project)
ee.Initialize(project='mexico-search')

app = Flask(__name__)

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        lon = data["lon"]
        lat = data["lat"]
        radius = data["radius"] * 1000  # km → meters
        baseline_start = data["baseline_start"]
        baseline_end = data["baseline_end"]
        recent_start = data["recent_start"]
        recent_end = data["recent_end"]
        thresholdFactor = 2.5  # lower threshold for testing / can be parameterized
        scale = 100

        # Target area
        center = ee.Geometry.Point([lon, lat])
        targetArea = center.buffer(radius)

        # Sentinel-1 collection
        s1Collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
            .filterBounds(targetArea) \
            .filter(ee.Filter.eq('instrumentMode', 'IW')) \
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')) \
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH')) \
            .select(['VV','VH'])

        # Filtered date ranges
        baselineCollection = s1Collection.filterDate(baseline_start, baseline_end)
        recentCollection = s1Collection.filterDate(recent_start, recent_end)

        # Safe mean (returns an Image)
        def safeMean(collection):
            return ee.Algorithms.If(
                collection.size().gt(0),
                collection.mean(),
                ee.Image([0,0]).rename(['VV','VH'])
            )

        baseline = ee.Image(safeMean(baselineCollection))
        recent = ee.Image(safeMean(recentCollection))

        # Standard deviation (avoid zero)
        stdDev = baselineCollection.reduce(ee.Reducer.stdDev()).max(1e-6)
        anomalies = recent.subtract(baseline).divide(stdDev).rename(['VV','VH'])

        anomaliesVV = anomalies.select('VV').abs().gt(thresholdFactor).clip(targetArea)
        anomaliesVH = anomalies.select('VH').abs().gt(thresholdFactor).clip(targetArea)

        # Population image (kept for priority computation)
        pop = ee.ImageCollection("WorldPop/GP/100m/pop") \
            .filter(ee.Filter.eq('year', 2020)) \
            .first() \
            .select('population') \
            .clip(targetArea)

        # (Optional) don't mask by population during debugging; comment/uncomment as needed
        # landMask = pop.gt(0)
        # anomaliesVV = anomaliesVV.updateMask(landMask)
        # anomaliesVH = anomaliesVH.updateMask(landMask)

        # Combine anomalies (Python EE)
        combinedAnomaly = anomaliesVV.Or(anomaliesVH)

        # Debug: collection sizes
        baseline_count = baselineCollection.size().getInfo()
        recent_count = recentCollection.size().getInfo()

        # Debug: anomaly pixel counts (sum of mask values)
        def safe_sum_count(image, band_name):
            try:
                val = image.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=targetArea,
                    scale=scale,
                    tileScale=4,
                    maxPixels=1e8
                ).get(band_name).getInfo()
                # If getInfo returned None, normalize to 0
                return val if val is not None else 0
            except Exception:
                return 0

        vv_anomaly_count = safe_sum_count(anomaliesVV, 'VV')
        vh_anomaly_count = safe_sum_count(anomaliesVH, 'VH')

        debug_info = {
            "baseline_count": baseline_count,
            "recent_count": recent_count,
            "vv_anomaly_pixels": vv_anomaly_count,
            "vh_anomaly_pixels": vh_anomaly_count
        }

        # Vectorize
        clustersVector = combinedAnomaly.toInt().reduceToVectors(
            geometry=targetArea,
            scale=scale,
            geometryType='polygon',
            eightConnected=True,
            maxPixels=1e8
        )

        # Compute priority (attach properties to each feature)
        def compute_priority(f):
            vvMean = anomaliesVV.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=f.geometry(),
                scale=scale,
                tileScale=4,
                maxPixels=1e8
            ).get('VV')
            popSum = pop.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=f.geometry(),
                scale=scale,
                tileScale=4,
                maxPixels=1e8
            ).get('population')
            # Some regions may return None for vvMean or popSum; keep them as-is (EE objects)
            return f.set({
                'VV_mean': vvMean,
                'population_sum': popSum,
                'priority': ee.Number(vvMean).multiply(popSum)
            })

        clustersWithPriority = clustersVector.map(compute_priority)

        # Top N clusters
        topN = 10
        top_clusters = clustersWithPriority.sort('priority', False).limit(topN)

        # Convert EE FeatureCollection to Python dict via getInfo() and build GeoJSON-like features
        clusters_info = top_clusters.getInfo()  # dict
        features = []
        if clusters_info and 'features' in clusters_info:
            for feat in clusters_info['features']:
                # feat is a dict with 'geometry' and 'properties'
                geometry = feat.get('geometry')
                properties = feat.get('properties', {}) or {}

                # properties may contain EE serialization quirks; keep as-is (numbers/null)
                features.append({
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": properties
                })

        return jsonify({"clusters": features, "debug": debug_info})

    except Exception as e:
        # Return the exception string for debugging (avoid exposing secrets in production)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
