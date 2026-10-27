"""Time-aware, conservative assignment. No image, model, or database dependencies."""
import math

def center(box):
    return ((box[0]+box[2])/2.0, (box[1]+box[3])/2.0)

def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

def iou(a, b):
    intersection = max(0.0, min(a[2],b[2])-max(a[0],b[0])) * max(0.0, min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union > 0 else 0.0

def minimum_assignment(costs):
    """Minimum total cost for rows <= columns; dummy columns represent no match."""
    if not costs:
        return []
    n, m = len(costs), len(costs[0])
    if m < n:
        raise ValueError("Not enough assignment columns")
    u, v, p, way = [0.0]*(n+1), [0.0]*(m+1), [0]*(m+1), [0]*(m+1)
    for row in range(1,n+1):
        p[0] = row
        j0 = 0
        minimum, used = [float("inf")]*(m+1), [False]*(m+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1,m+1):
                if not used[j]:
                    current = costs[i0-1][j-1]-u[i0]-v[j]
                    if current < minimum[j]:
                        minimum[j], way[j] = current, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(m+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1]*n
    for j in range(1,m+1):
        if p[j]:
            result[p[j]-1] = j-1
    return result

class Tracker:
    def __init__(self, config):
        self.config = dict(config)
        self.tracks = {}
        self.next_id = 0

    def clear(self):
        retired = sorted(self.tracks)
        self.tracks = {}
        return retired

    def update(self, detections, now):
        expired = sorted(key for key,t in self.tracks.items()
                         if now-t["last_seen"] > self.config["max_idle_seconds"])
        for key in expired:
            del self.tracks[key]
        ids = sorted(self.tracks)
        large, unmatched = 1000000.0, 2.0
        costs = []
        for key in ids:
            track = self.tracks[key]
            dt = now-track["last_seen"]
            prediction_dt = min(dt, self.config["prediction_horizon_seconds"])
            predicted = tuple(track["center"][i]+track["velocity"][i]*prediction_dt for i in (0,1))
            row = []
            for det in detections:
                box = det["box"]
                c = center(box)
                old_area = (track["box"][2]-track["box"][0])*(track["box"][3]-track["box"][1])
                area = (box[2]-box[0])*(box[3]-box[1])
                ratio = area/old_area
                d = distance(c,predicted)
                gate = self.config["max_distance"]
                if not track["observed"]:
                    gate = min(gate,self.config["reacquire_distance"])
                eligible = d <= gate and .25 <= ratio <= 4.0
                row.append(d/gate + .5*(1.0-iou(track["box"],box)) if eligible else large)
            costs.append(row)
        # Ambiguity is deliberately conservative: never transfer entry on a near tie.
        ambiguous_rows, ambiguous_columns = set(), set()
        margin = self.config["ambiguity_margin"]
        for i,row in enumerate(costs):
            valid = sorted((cost,j) for j,cost in enumerate(row) if cost < unmatched)
            if len(valid)>1 and valid[1][0]-valid[0][0] <= margin:
                ambiguous_rows.add(i)
                ambiguous_columns.update(j for cost,j in valid if cost-valid[0][0] <= margin)
        for j in range(len(detections)):
            valid = sorted((costs[i][j],i) for i in range(len(ids)) if costs[i][j] < unmatched)
            if len(valid)>1 and valid[1][0]-valid[0][0] <= margin:
                ambiguous_columns.add(j)
                ambiguous_rows.update(i for cost,i in valid if cost-valid[0][0] <= margin)
        matrix = []
        for i,row in enumerate(costs):
            matrix.append([large if i in ambiguous_rows or j in ambiguous_columns else cost
                           for j,cost in enumerate(row)] + [unmatched]*len(ids))
        assignments = minimum_assignment(matrix)
        matched, new_ids = set(), []
        for i,key in enumerate(ids):
            track = self.tracks[key]
            j = assignments[i]
            if j < len(detections) and j >= 0 and matrix[i][j] < unmatched:
                det = detections[j]
                c = center(det["box"])
                dt = now-track["last_seen"]
                velocity = tuple((c[k]-track["center"][k])/dt for k in (0,1))
                speed = math.hypot(*velocity)
                if speed > self.config["max_velocity"]:
                    velocity = tuple(v*self.config["max_velocity"]/speed for v in velocity)
                previous_observed = track["observed"]
                track.update(velocity=tuple(.5*track["velocity"][k]+.5*velocity[k] for k in (0,1)),
                             box=list(det["box"]), center=c, last_seen_gap=dt, last_seen=now,
                             observed=True, detection_index=j, new_track=False,
                             reacquired=not previous_observed, matching_cost=matrix[i][j])
                matched.add(j)
            else:
                track.update(observed=False,detection_index=None,new_track=False,reacquired=False,
                             matching_cost=None)
        untracked = []
        for j,det in enumerate(detections):
            if j in matched:
                continue
            if len(self.tracks) >= self.config["max_tracks"]:
                untracked.append(j)
                continue
            key = self.next_id
            self.next_id += 1
            self.tracks[key] = {"id":key,"box":list(det["box"]),"center":center(det["box"]),
                                "velocity":(0.0,0.0),"first_seen":now,"last_seen":now,
                                "last_seen_gap":None,"observed":True,"detection_index":j,
                                "new_track":True,"reacquired":False,"matching_cost":None}
            new_ids.append(key)
        return {"tracks":self.tracks,"expired_ids":expired,"new_ids":new_ids,
                "ambiguous_detection_indices":sorted(ambiguous_columns),"untracked_indices":untracked}
