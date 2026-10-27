"""Conservative identity tracking: retire ambiguous identities, never transfer evidence."""
import math
from ..tracking_v4 import Tracker,center,distance,iou,minimum_assignment

class TrackerD(Tracker):
    proximity=.08

    def update(self,detections,now):
        expired=[key for key,t in self.tracks.items() if now-t["last_seen"]>self.config["max_idle_seconds"]]
        for key in expired:del self.tracks[key]
        ids=sorted(self.tracks)
        predicted={}
        for key in ids:
            t=self.tracks[key];dt=min(now-t["last_seen"],self.config["prediction_horizon_seconds"])
            predicted[key]=tuple(t["center"][k]+t["velocity"][k]*dt for k in (0,1))
        uncertain_tracks=set();uncertain_detections=set()
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                first,second=self.tracks[a],self.tracks[b]
                r=tuple(first["center"][k]-second["center"][k] for k in (0,1))
                d=tuple((predicted[a][k]-first["center"][k])-(predicted[b][k]-second["center"][k]) for k in (0,1))
                denom=d[0]**2+d[1]**2
                fraction=0.0 if denom==0 else max(0.0,min(1.0,-sum(r[k]*d[k] for k in (0,1))/denom))
                closest=math.hypot(r[0]+fraction*d[0],r[1]+fraction*d[1])
                if closest<self.proximity:
                    uncertain_tracks.update((a,b))
        for i,a in enumerate(detections):
            for j in range(i+1,len(detections)):
                if distance(center(a["box"]),center(detections[j]["box"]))<self.proximity:
                    uncertain_detections.update((i,j))
        large,unmatched=1e6,2.0
        raw={}
        for key in ids:
            track=self.tracks[key];row=[]
            gate=self.config["max_distance"] if track["observed"] else self.config["reacquire_distance"]
            old_area=(track["box"][2]-track["box"][0])*(track["box"][3]-track["box"][1])
            for det in detections:
                area=(det["box"][2]-det["box"][0])*(det["box"][3]-det["box"][1])
                d=distance(center(det["box"]),predicted[key])
                valid=d<=gate and .25<=area/old_area<=4
                row.append(d/gate+.1*(1-iou(track["box"],det["box"])) if valid else large)
            raw[key]=row
        for key,row in raw.items():
            choices=sorted((cost,j) for j,cost in enumerate(row) if cost<unmatched)
            if len(choices)>1 and choices[1][0]-choices[0][0]<=self.config["ambiguity_margin"]:
                uncertain_tracks.add(key)
                uncertain_detections.update(j for cost,j in choices if cost-choices[0][0]<=self.config["ambiguity_margin"])
        for j in range(len(detections)):
            choices=sorted((raw[key][j],key) for key in ids if raw[key][j]<unmatched)
            if len(choices)>1 and choices[1][0]-choices[0][0]<=self.config["ambiguity_margin"]:
                uncertain_detections.add(j)
                uncertain_tracks.update(key for cost,key in choices if cost-choices[0][0]<=self.config["ambiguity_margin"])
        # Close the ambiguous connected component before any assignment or state transfer.
        changed=True
        while changed:
            before=(len(uncertain_tracks),len(uncertain_detections))
            for key in ids:
                for j,cost in enumerate(raw[key]):
                    if cost<unmatched and (key in uncertain_tracks or j in uncertain_detections):
                        uncertain_tracks.add(key);uncertain_detections.add(j)
            changed=before!=(len(uncertain_tracks),len(uncertain_detections))
        retired=sorted(uncertain_tracks)
        for key in retired:del self.tracks[key]
        safe_ids=sorted(self.tracks)
        matrix=[[large if j in uncertain_detections else cost for j,cost in enumerate(raw[key])]+
                [unmatched]*len(safe_ids) for key in safe_ids]
        assignments=minimum_assignment(matrix)
        matched=set();new_ids=[]
        for i,key in enumerate(safe_ids):
            track=self.tracks[key];j=assignments[i]
            if 0<=j<len(detections) and matrix[i][j]<unmatched:
                det=detections[j];c=center(det["box"]);dt=now-track["last_seen"]
                velocity=tuple((c[k]-track["center"][k])/dt for k in (0,1))
                speed=math.hypot(*velocity)
                if speed>self.config["max_velocity"]:
                    velocity=tuple(v*self.config["max_velocity"]/speed for v in velocity)
                old_observed=track["observed"]
                track.update(box=list(det["box"]),center=c,
                             velocity=tuple(.5*track["velocity"][k]+.5*velocity[k] for k in (0,1)),
                             last_seen=now,last_seen_gap=dt,observed=True,detection_index=j,
                             new_track=False,reacquired=not old_observed,matching_cost=matrix[i][j])
                matched.add(j)
            else:
                track.update(observed=False,detection_index=None,new_track=False,reacquired=False,matching_cost=None)
        untracked=[]
        for j,det in enumerate(detections):
            if j in matched or j in uncertain_detections:continue
            if len(self.tracks)>=self.config["max_tracks"]:untracked.append(j);continue
            key=self.next_id;self.next_id+=1
            self.tracks[key]={"id":key,"box":list(det["box"]),"center":center(det["box"]),
                              "velocity":(0.0,0.0),"first_seen":now,"last_seen":now,"last_seen_gap":None,
                              "observed":True,"detection_index":j,"new_track":True,"reacquired":False,"matching_cost":None}
            new_ids.append(key)
        return {"tracks":self.tracks,"expired_ids":expired,"new_ids":new_ids,"uncertain_track_ids":retired,
                "ambiguous_detection_indices":sorted(uncertain_detections),"untracked_indices":untracked}
