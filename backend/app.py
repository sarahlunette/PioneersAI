# from flask import Flask, request, jsonify
# import ee
# from flask_cors import CORS
# import csv
# import os

# # Initialize Earth Engine
# ee.Initialize(project='mexico-search')

# app = Flask(__name__)
# CORS(app)  # Enable CORS

# @app.route("/analyze", methods=["POST"])
# def analyze():
#     try:
#         data = request.get_json()
#         lon = data["lon"]
#         lat = data["lat"]
#         radius = data["radius"] * 1000  # km → meters
#         baseline_start = data["baseline_start"]
#         baseline_end = data["baseline_end"]
#         recent_start = data["recent_start"]
#         recent_end = data["recent_end"]

#         thresholdFactor = 2.5
#         scale = 100

#         # ------------------------------
#         # TARGET AREA
#         # ------------------------------
#         center = ee.Geometry.Point([lon, lat])
#         targetArea = center.buffer(radius)

#         # ------------------------------
#         # SENTINEL-1 COLLECTION
#         # ------------------------------
#         s1Collection = (
#             ee.ImageCollection('COPERNICUS/S1_GRD')
#                 .filterBounds(targetArea)
#                 .filter(ee.Filter.eq('instrumentMode', 'IW'))
#                 .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
#                 .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
#                 .select(['VV', 'VH'])
#         )

#         baselineCollection = s1Collection.filterDate(baseline_start, baseline_end)
#         recentCollection = s1Collection.filterDate(recent_start, recent_end)

#         # ------------------------------
#         # SAFE MEAN
#         # ------------------------------
#         def safeMean(collection):
#             return ee.Image(
#                 ee.Algorithms.If(
#                     collection.size().gt(0),
#                     collection.mean(),
#                     ee.Image([0, 0]).rename(['VV', 'VH'])
#                 )
#             )

#         baseline = safeMean(baselineCollection)
#         recent = safeMean(recentCollection)

#         # ------------------------------
#         # Z-SCORE ANOMALIES
#         # ------------------------------
#         stdDev = baselineCollection.reduce(ee.Reducer.stdDev()).max(1e-6)
#         anomalies = recent.subtract(baseline).divide(stdDev).rename(['VV', 'VH'])

#         anomaliesVV = anomalies.select('VV').abs().gt(thresholdFactor).clip(targetArea)
#         anomaliesVH = anomalies.select('VH').abs().gt(thresholdFactor).clip(targetArea)

#         # ------------------------------
#         # COMBINED ANOMALY
#         # ------------------------------
#         combinedAnomaly = anomaliesVV.Or(anomaliesVH).updateMask(anomaliesVV.Or(anomaliesVH))

#         # ------------------------------
#         # POPULATION
#         # ------------------------------
#         pop = (
#             ee.ImageCollection('CIESIN/GPWv411/GPW_Population_Count')
#             .first()
#             .select('population_count')
#             .resample('bilinear')
#             .clip(targetArea)
#         )

#         # ------------------------------
#         # VECTORIZATION
#         # ------------------------------
#         clustersVector = combinedAnomaly.toInt().reduceToVectors(
#             geometry=targetArea,
#             scale=scale,
#             geometryType='polygon',
#             eightConnected=True,
#             maxPixels=1e9
#         )

#         # ------------------------------
#         # COMPUTE PRIORITY
#         # ------------------------------
#         def compute_priority(f):
#             vvMean = anomaliesVV.reduceRegion(
#                 reducer=ee.Reducer.mean(),
#                 geometry=f.geometry(),
#                 scale=scale,
#                 tileScale=4,
#                 maxPixels=1e9
#             ).get('VV')

#             popSum = pop.reduceRegion(
#                 reducer=ee.Reducer.sum(),
#                 geometry=f.geometry(),
#                 scale=scale,
#                 tileScale=4,
#                 maxPixels=1e9
#             ).get('population_count')

#             # Count pixels in cluster
#             pixel_count = f.geometry().area().divide(scale * scale)

#             # Priority normalized by pixel count
#             priority = ee.Number(vvMean).multiply(popSum).divide(pixel_count)

#             return f.set({
#                 'VV_mean': vvMean,
#                 'population_sum': popSum,
#                 'pixel_count': pixel_count,
#                 'priority': priority
#             })

#         clustersWithPriority = clustersVector.map(compute_priority)

#         # ------------------------------
#         # TOP 10 CLUSTERS
#         # ------------------------------
#         top10 = clustersWithPriority.sort('priority', False).limit(10)

#         # ------------------------------
#         # COLOR RAMP
#         # ------------------------------
#         colors = ee.List(['yellow', 'orange', 'red'])
#         top10List = top10.toList(10)

#         def add_color(i):
#             i = ee.Number(i)
#             f = ee.Feature(top10List.get(i))
#             colorIndex = (
#                 i.divide(ee.Number(top10List.size()).subtract(1))
#                 .multiply(colors.size().subtract(1))
#                 .round()
#             )
#             return f.set({'color': colors.get(colorIndex)})

#         coloredFC = ee.FeatureCollection(
#             ee.List.sequence(0, top10List.size().subtract(1)).map(add_color)
#         )

#         # ------------------------------
#         # CSV GENERATION
#         # ------------------------------
#         fc_info = coloredFC.getInfo()
#         csv_file = os.path.join(os.getcwd(), "top10_clusters.csv")

#         try:
#             with open(csv_file, mode="w", newline="") as f:
#                 writer = csv.writer(f)
#                 writer.writerow(["id", "VV_mean", "population_sum", "pixel_count", "priority", "color"])
#                 for feat in fc_info.get("features", []):
#                     props = feat.get("properties", {})
#                     writer.writerow([
#                         props.get("system:index", ""),
#                         props.get("VV_mean", 0),
#                         props.get("population_sum", 0),
#                         props.get("pixel_count", 0),
#                         props.get("priority", 0),
#                         props.get("color", "")
#                     ])
#         except Exception as e:
#             print("CSV write error:", e)

#         # ------------------------------
#         # RETURN JSON
#         # ------------------------------
#         features = []
#         for f in fc_info.get("features", []):
#             features.append({
#                 "type": "Feature",
#                 "geometry": f.get("geometry"),
#                 "properties": f.get("properties")
#             })

#         return jsonify({
#             "clusters": features,
#             "debug": {
#                 "baseline_count": baselineCollection.size().getInfo(),
#                 "recent_count": recentCollection.size().getInfo()
#             },
#             "csv_file": csv_file
#         })

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# if __name__ == "__main__":
#     app.run(debug=True)




# from flask import Flask, request, jsonify
# import ee
# from flask_cors import CORS
# import traceback

# # Initialize Earth Engine (use your project)
# ee.Initialize(project='mexico-search')

# app = Flask(__name__)
# CORS(app)  # Enable CORS for all routes

# @app.route("/analyze", methods=["POST"])
# def analyze():
#     try:
#         data = request.get_json()
#         lon = data["lon"]
#         lat = data["lat"]
#         radius = data["radius"] * 1000  # km → meters
#         baseline_start = data["baseline_start"]
#         baseline_end = data["baseline_end"]
#         recent_start = data["recent_start"]
#         recent_end = data["recent_end"]

#         thresholdFactor = 2.5
#         scale = 100

#         # ------------------------------
#         # TARGET AREA
#         # ------------------------------
#         center = ee.Geometry.Point([lon, lat])
#         targetArea = center.buffer(radius)

#         # ------------------------------
#         # SENTINEL-1 COLLECTION
#         # ------------------------------
#         s1Collection = (
#             ee.ImageCollection('COPERNICUS/S1_GRD')
#             .filterBounds(targetArea)
#             .filter(ee.Filter.eq('instrumentMode', 'IW'))
#             .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
#             .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
#             .select(['VV', 'VH'])
#         )

#         baselineCollection = s1Collection.filterDate(baseline_start, baseline_end)
#         recentCollection = s1Collection.filterDate(recent_start, recent_end)

#         # Check if collections are empty
#         baseline_size = baselineCollection.size().getInfo()
#         recent_size = recentCollection.size().getInfo()
#         if baseline_size == 0 or recent_size == 0:
#             return jsonify({"error": "No Sentinel-1 images for the given area/date",
#                             "baseline_size": baseline_size,
#                             "recent_size": recent_size}), 400

#         # ------------------------------
#         # SAFE MEAN
#         # ------------------------------
#         def safeMean(collection):
#             return ee.Image(
#                 ee.Algorithms.If(
#                     collection.size().gt(0),
#                     collection.mean(),
#                     ee.Image([0, 0]).rename(['VV', 'VH'])
#                 )
#             )

#         baseline = safeMean(baselineCollection)
#         recent = safeMean(recentCollection)

#         # ------------------------------
#         # Z-SCORE ANOMALIES
#         # ------------------------------
#         stdDev = baselineCollection.reduce(ee.Reducer.stdDev()).max(1e-6)
#         anomalies = recent.subtract(baseline).divide(stdDev).rename(['VV', 'VH'])

#         anomaliesVV = anomalies.select('VV').abs().gt(thresholdFactor).clip(targetArea)
#         anomaliesVH = anomalies.select('VH').abs().gt(thresholdFactor).clip(targetArea)

#         # ------------------------------
#         # OVERLAP (VV ∧ VH)
#         # ------------------------------
#         overlap = anomaliesVV.And(anomaliesVH).updateMask(anomaliesVV.And(anomaliesVH))

#         # ------------------------------
#         # COMBINED ANOMALY (VV ∨ VH)
#         # ------------------------------
#         combinedAnomaly = anomaliesVV.Or(anomaliesVH).updateMask(anomaliesVV.Or(anomaliesVH))

#         # ------------------------------
#         # POPULATION
#         # ------------------------------
#         pop = (
#             ee.ImageCollection('CIESIN/GPWv411/GPW_Population_Count')
#             .first()
#             .select('population_count')
#             .resample('bilinear')
#             .clip(targetArea)
#         )

#         # ------------------------------
#         # DEBUG METRICS
#         # ------------------------------
#         def safe_sum(image, band):
#             try:
#                 v = image.reduceRegion(
#                     reducer=ee.Reducer.sum(),
#                     geometry=targetArea,
#                     scale=scale,
#                     tileScale=4,
#                     maxPixels=1e9
#                 ).get(band).getInfo()
#                 return v or 0
#             except Exception as e:
#                 print("safe_sum failed:", e)
#                 return 0

#         debug_info = {
#             "baseline_count": baseline_size,
#             "recent_count": recent_size,
#             "vv_anomaly_pixels": safe_sum(anomaliesVV, 'VV'),
#             "vh_anomaly_pixels": safe_sum(anomaliesVH, 'VH'),
#         }

#         # ------------------------------
#         # VECTORIZATION
#         # ------------------------------
#         clustersVector = combinedAnomaly.toInt().reduceToVectors(
#             geometry=targetArea,
#             scale=scale,
#             geometryType='polygon',
#             eightConnected=True,
#             maxPixels=1e9
#         )

#         # ------------------------------
#         # COMPUTE PRIORITY
#         # ------------------------------
#         def compute_priority(f):
#             vvMean = anomaliesVV.reduceRegion(
#                 reducer=ee.Reducer.mean(),
#                 geometry=f.geometry(),
#                 scale=scale,
#                 tileScale=4,
#                 maxPixels=1e9
#             ).get('VV')

#             popSum = pop.reduceRegion(
#                 reducer=ee.Reducer.sum(),
#                 geometry=f.geometry(),
#                 scale=scale,
#                 tileScale=4,
#                 maxPixels=1e9
#             ).get('population_count')

#             return f.set({
#                 'VV_mean': vvMean,
#                 'population_sum': popSum,
#                 'priority': ee.Number(vvMean).multiply(popSum)
#             })

#         clustersWithPriority = clustersVector.map(compute_priority)

#         # ------------------------------
#         # TOP 10 CLUSTERS
#         # ------------------------------
#         top10 = clustersWithPriority.sort('priority', False).limit(10)

#         # ------------------------------
#         # COLOR RAMP
#         # ------------------------------
#         colors = ee.List(['yellow', 'orange', 'red'])
#         top10List = top10.toList(10)

#         def add_color(i):
#             i = ee.Number(i)
#             f = ee.Feature(top10List.get(i))
#             colorIndex = (
#                 i.divide(ee.Number(top10List.size()).subtract(1))
#                 .multiply(colors.size().subtract(1))
#                 .round()
#             )
#             return f.set({'color': colors.get(colorIndex)})

#         coloredFC = ee.FeatureCollection(
#             ee.List.sequence(0, top10List.size().subtract(1)).map(add_color)
#         )

#         # ------------------------------
#         # CSV EXPORT (top 10 clusters as dict)
#         # ------------------------------
#         fc_info = coloredFC.getInfo()
#         csv_data = []
#         for f in fc_info.get("features", []):
#             props = f.get("properties", {})
#             geom = f.get("geometry", {})
#             csv_data.append({**props, "geometry": geom})

#         # ------------------------------
#         # Convert to GeoJSON for frontend
#         # ------------------------------
#         features = []
#         for f in fc_info.get("features", []):
#             features.append({
#                 "type": "Feature",
#                 "geometry": f.get("geometry"),
#                 "properties": f.get("properties", {}),
#             })

#         return jsonify({
#             "clusters": features,
#             "debug": debug_info,
#             "csv": csv_data
#         })

#     except Exception as e:
#         traceback.print_exc()
#         return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# if __name__ == "__main__":
#     app.run(debug=True)




from flask import Flask, request, jsonify
import ee
from flask_cors import CORS

# Initialize Earth Engine (uses your provided project)
ee.Initialize(project='mexico-search')

app = Flask(__name__)
CORS(app) 

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

        thresholdFactor = 2.5
        scale = 100

        # ------------------------------
        # TARGET AREA
        # ------------------------------
        center = ee.Geometry.Point([lon, lat])
        targetArea = center.buffer(radius)

        # ------------------------------
        # SENTINEL-1 COLLECTION
        # ------------------------------
        s1Collection = (
            ee.ImageCollection('COPERNICUS/S1_GRD')
                .filterBounds(targetArea)
                .filter(ee.Filter.eq('instrumentMode', 'IW'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                .select(['VV', 'VH'])
        )

        baselineCollection = s1Collection.filterDate(baseline_start, baseline_end)
        recentCollection = s1Collection.filterDate(recent_start, recent_end)

        # ------------------------------
        # SAFE MEAN
        # ------------------------------
        def safeMean(collection):
            return ee.Image(
                ee.Algorithms.If(
                    collection.size().gt(0),
                    collection.mean(),
                    ee.Image([0, 0]).rename(['VV', 'VH'])
                )
            )

        baseline = safeMean(baselineCollection)
        recent = safeMean(recentCollection)

        # ------------------------------
        # Z-SCORE ANOMALIES
        # ------------------------------
        stdDev = baselineCollection.reduce(ee.Reducer.stdDev()).max(1e-6)
        anomalies = recent.subtract(baseline).divide(stdDev).rename(['VV', 'VH'])

        anomaliesVV = anomalies.select('VV').abs().gt(thresholdFactor).clip(targetArea)
        anomaliesVH = anomalies.select('VH').abs().gt(thresholdFactor).clip(targetArea)

        # ------------------------------
        # OVERLAP (VV ∧ VH)
        # ------------------------------
        overlap = anomaliesVV.And(anomaliesVH).updateMask(
            anomaliesVV.And(anomaliesVH)
        )

        # ------------------------------
        # COMBINED ANOMALY (VV ∨ VH)
        # ------------------------------
        combinedAnomaly = anomaliesVV.Or(anomaliesVH).updateMask(
            anomaliesVV.Or(anomaliesVH)
        )

        # ------------------------------
        # POPULATION — SAME AS GEE SCRIPT
        # ------------------------------
        pop = (
            ee.ImageCollection('CIESIN/GPWv411/GPW_Population_Count')
            .first()
            .select('population_count')
            .resample('bilinear')
            .clip(targetArea)
        )

        # ------------------------------
        # DEBUG METRICS
        # ------------------------------
        baseline_count = baselineCollection.size().getInfo()
        recent_count = recentCollection.size().getInfo()

        def safe_sum(image, band):
            try:
                v = image.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=targetArea,
                    scale=scale,
                    tileScale=4,
                    maxPixels=1e9
                ).get(band).getInfo()
                return v or 0
            except:
                return 0

        vv_anomaly_count = safe_sum(anomaliesVV, 'VV')
        vh_anomaly_count = safe_sum(anomaliesVH, 'VH')

        debug_info = {
            "baseline_count": baseline_count,
            "recent_count": recent_count,
            "vv_anomaly_pixels": vv_anomaly_count,
            "vh_anomaly_pixels": vh_anomaly_count,
        }

        # ------------------------------
        # VECTORIZATION
        # ------------------------------
        clustersVector = combinedAnomaly.toInt().reduceToVectors(
            geometry=targetArea,
            scale=scale,
            geometryType='polygon',
            eightConnected=True,
            maxPixels=1e9
        )

        # ------------------------------
        # COMPUTE PRIORITY
        # ------------------------------
        def compute_priority(f):
            vvMean = anomaliesVV.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=f.geometry(),
                scale=scale,
                tileScale=4,
                maxPixels=1e9
            ).get('VV')

            popSum = pop.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=f.geometry(),
                scale=scale,
                tileScale=4,
                maxPixels=1e9
            ).get('population_count')

            return f.set({
                'VV_mean': vvMean,
                'population_sum': popSum,
                'priority': ee.Number(vvMean).multiply(popSum)
            })
            # # Count the number of pixels in the feature (cluster)
            # pixel_count = f.geometry().area().divide(scale*scale)  # approximate pixel count based on scale

            # # Compute priority normalized by number of pixels
            # priority = ee.Number(vvMean).multiply(popSum).divide(pixel_count)

            # return f.set({
            #     'VV_mean': vvMean,
            #     'population_sum': popSum,
            #     'pixel_count': pixel_count,
            #     'priority': priority
            # })

        clustersWithPriority = clustersVector.map(compute_priority)

        # ------------------------------
        # TOP 10 CLUSTERS
        # ------------------------------
        top10 = clustersWithPriority.sort('priority', False).limit(10)

        # ------------------------------
        # COLOR RAMP (yellow → orange → red)
        # ------------------------------
        colors = ee.List(['yellow', 'orange', 'red'])
        top10List = top10.toList(10)



        def add_color(i):
            i = ee.Number(i)
            f = ee.Feature(top10List.get(i))

            colorIndex = (
                i.divide(ee.Number(top10List.size()).subtract(1))
                .multiply(colors.size().subtract(1))
                .round()
            )

            return f.set({'color': colors.get(colorIndex)})

        coloredFC = ee.FeatureCollection(
            ee.List.sequence(0, top10List.size().subtract(1)).map(add_color)
        )

        # ------------------------------
        # Convert to Python objects
        # ------------------------------
        fc_info = coloredFC.getInfo()

        features = []
        for f in fc_info.get("features", []):
            features.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": f["properties"],
            })

        return jsonify({
            "clusters": features,
            "debug": debug_info
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
