import pandas as pd
import numpy as np
import random
import os
import lightgbm as lgb
import sys
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
from math import sqrt
from sklearn.externals import joblib
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.utils import compute_sample_weight
from format_features import create_album_score_lookup_table, assign_value_redesigned, create_artist_score_lookup_table
from format_features import baysianEncodeFeature
from format_features import format_features, assign_artist_features_inplace
from sklearn.model_selection import train_test_split
from typecast_features import cast_cat_dtype_to_cat_codes
from typecast_features import typecast_features
from utils import  get_data, print_rmse, append_metadata

import argparse

parser = argparse.ArgumentParser(description='Script to train and generate predictions')
parser.add_argument('--data', required=True, help='Directory contain path to raw info data of ZALO')
parser.add_argument('--csv_metadata_path', type=str, required=True, help='.csv file contain generated metadata features')
parser.add_argument('--save_model_dir', default="saved_models",type=str, help='Directory contained trained model')
parser.add_argument('--save_submission_file', type=str, required=True, help='.csv submission file')


# Random seed
np.random.seed(1)
random.seed(1)

# Parse arguments
args = parser.parse_args()

# Get raw infomation of data
df = get_data(args.data)

# Append the generated metadata to dataframe
df = append_metadata(df, args.csv_metadata_path)

# Format and type cast feature
df = format_features(df)
all_features_in_order_list, df = typecast_features(df, cast_to_catcode=True)

# Remove len =0
df = df[(df.length>0) | (df.num_same_title==1)]

df = assign_artist_features_inplace(df)


chosen_features = ["album_right", "istrack11", "no_artist", "no_composer", "freq_artist", "freq_composer", "year",
                   "month", "hour", "day", "len_of_songname",
                   "isRemix", "isOST", "isBeat", "isVersion", "isCover", "num_song_release_in_final_month",
                   "length", "genre", "track", "album_artist", "islyric", "album_artist_contain_artistname",
                   "len_album_name", "isRemixAlbum", "isOSTAlbum", "isSingleAlbum", "album_name_is_title_name",
                   "isBeatAlbum", "isCoverAlbum", "artist_name", "composers_name", "copyright",
                   "artist_id_min_cat", "composers_id_min_cat", "artist_id_max_cat", "composers_id_max_cat",
                   "freq_artist_min", "freq_composer_min", "dayofyear", "weekday", "isHoliday",
                   "num_album_per_min_artist", "num_album_per_min_composer",
                   "numsongInAlbum", "isSingleAlbum_onesong", "artist_mean_id",
                   "artist_std_id", "artist_count_id", "title_cat", "num_same_title", "ID"]

chosen_features += ["predicted_label"]
df_train = df[df.dataset == "train"]
df_test = df[df.dataset == "test"]

param = {
    'bagging_freq': 20,
    'bagging_fraction': 0.95, 'boost_from_average': 'false',
    'boost': 'gbdt', 'feature_fraction': 0.1, 'learning_rate': 0.001,
    'max_depth': -1, 'metric': 'root_mean_squared_error', 'min_data_in_leaf': 5,
    'num_leaves': 50,
    'num_threads': 8, 'tree_learner': 'serial', 'objective': 'regression',
    'reg_alpha': 0.1002650970728192, 'reg_lambda': 0.1003427518866501, 'verbosity': 1,
    "seed": 99999,
    "use_missing": True
}


from math import sqrt

folds = StratifiedKFold(n_splits=10, shuffle=True, random_state=99999)
oof = np.zeros(len(df_train))
predictions = np.zeros(len(df_test))
labels = df_train.label
best_stopping_iterations_list = []
for fold_, (trn_idx, val_idx) in enumerate(folds.split(df_train.values, df_train.album_right.values)):
    print("Fold {}".format(fold_))
    
    # Create lookup table
    album_lookup_table = create_album_score_lookup_table(df_train.iloc[trn_idx])
    artist_lookup_table = create_artist_score_lookup_table(df_train.iloc[trn_idx])
    df_train["predicted_label"] = [assign_value_redesigned(album_lookup_table, artist_lookup_table, r) for i, r in
                                   df_train.iterrows()]
    df_test["predicted_label"] = [assign_value_redesigned(album_lookup_table, artist_lookup_table, r) for i, r in
                                  df_test.iterrows()]
    print("No imputation: Train\n")
    print(df_train.iloc[trn_idx][chosen_features].isnull().sum())
    print("No imputation: Val\n")
    print(df_train.iloc[val_idx][chosen_features].isnull().sum())
    print("No imputation: Test\n")
    print(df_test[chosen_features].isnull().sum())

    train_weights = compute_sample_weight('balanced', df_train.iloc[trn_idx].label)
    
    trn_data = lgb.Dataset(df_train.iloc[trn_idx][chosen_features],
                           label=labels.iloc[trn_idx],params={'verbose': -1},
                           free_raw_data=False,
                           weight=train_weights)
    val_data = lgb.Dataset(df_train.iloc[val_idx][chosen_features], label=labels.iloc[val_idx],params={'verbose': -1}, free_raw_data=False)
    
    # Train model and predict
    clf = lgb.train(param, trn_data, 1000000, valid_sets=[trn_data, val_data], verbose_eval=5000,
                    early_stopping_rounds=20000)
    oof[val_idx] = clf.predict(df_train.iloc[val_idx][chosen_features], num_iteration=clf.best_iteration)
    predictions += clf.predict(df_test[chosen_features], num_iteration=clf.best_iteration) / folds.n_splits
    best_stopping_iterations_list.append(clf.best_iteration)
    
    #Save model
    if not os.path.isdir(args.save_model_dir):
        os.makedirs(args.save_model_dir)
        print("Created folder to stores trained model")
    joblib.dump(clf, "/".join([args.save_model_dir , str(fold_)+".sav"]))
    print(f'Saved model {str(fold_)+".sav"}')

print("RMSE: {:<8.5f}".format(sqrt(mean_squared_error(df_train.label, oof))))
sub = pd.DataFrame({"ID": df_test.ID.values})
sub["label"] = predictions.round(decimals=4)
mean_rmse, std_rmse = print_rmse(df_train, oof)

# Save prediction file
root_dir_submission = os.path.split(args.save_submission_file)[0]
if not os.path.isdir(root_dir_submission):
    os.makedirs(root_dir_submission)
    print("Created folder storing submission file!")

sub.to_csv(args.save_submission_file, index=False, header=False)
print("The number of best number of iterations was:", np.array(best_stopping_iterations_list).mean(), "+/-", np.array(best_stopping_iterations_list).std())
