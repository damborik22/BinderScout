from sklearn.ensemble import RandomForestRegressor
from sklearn.discriminant_analysis import StandardScaler
from numpy import float64


class RandomForestModel:

    """Class for storing random forest model"""
    def __init__(self, regressor, features_mean: dict,
                 order:list, scaler=None):
        self.regressor = regressor
        self.features_mean = features_mean
        self.order = order
        self.scaler = scaler

    def predict(self, features):

        if self.scaler is not None:
            features = features.copy()
            features[self.order] = self.scaler.transform(features[self.order].astype(float64))

        return self.regressor.predict(features[self.order])
