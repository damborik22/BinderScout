from numpy import float64
from numpy import  where


class GradientBoostingClassifierWrapper:

    """Class for storing random forest model"""
    def __init__(self, classifier, features_mean: dict,
                 order:list, scaler=None, soluble_class=1):
        self.classifier = classifier
        self.features_mean = features_mean
        self.order = order
        self.scaler = scaler
        self.soluble_class = soluble_class

    def predict(self, features):

        if self.scaler is not None:
            features = features.copy()
            features[self.order] = self.scaler.transform(features[self.order].astype(float64))

        pred_prob = self.classifier.predict_proba(features[self.order])
        pos = where(self.classifier.classes_ == self.soluble_class)[0][0]
        pred = pred_prob[:, pos]

        return pred
